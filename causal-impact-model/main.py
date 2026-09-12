"""
Causal Impact portfolio module, command-line entry point.

Loads a weekly series from CSV, determines an intervention date (either
supplied on the command line or auto-discovered via spend-drop detection),
fits a BSTS counterfactual on the pre-period, forecasts into the post-period,
and writes the effect estimate plus the pointwise counterfactual to ./output.

In the original production system results were written to a data warehouse.
Here they are written to local CSV + JSON files instead.

Usage:
  python main.py --demo
      Run on the bundled synthetic series with automated intervention discovery.

  python main.py --input data/sample_series.csv --kpi conversions
      Same, on an explicit input file.

  python main.py --input my_series.csv --intervention-date 2023-10-02
      Skip auto-detection and analyse a specific intervention date.
"""


# The demos print box-drawing characters and arrows. A Windows console defaults
# to cp1252, which cannot encode them, so an unguarded print crashes the demo on
# a clean Windows machine. No-op on Linux and macOS.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import argparse
import csv
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Optional

from config import (
    DEFAULT_INPUT_CSV,
    DEFAULT_KPI,
    DEFAULT_OUTPUT_DIR,
    DETECTION_PARAMS,
    KPI_CONFIGS,
)
from data_prep import load_series_csv, prepare_spec, select_kpi_series
from model_runner import AnalysisResult, run_single_analysis

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("causal-impact")


# =============================================================================
# Local Export (warehouse write stubbed to local files)
# =============================================================================

def export_result(result: AnalysisResult, output_dir: str) -> tuple:
    """
    Write the analysis summary (JSON) and the pointwise time series (CSV) to
    the output directory. Returns the two paths written.
    """
    os.makedirs(output_dir, exist_ok=True)

    summary_path = os.path.join(output_dir, "analysis_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result.summary), f, indent=2, default=str)

    ts_path = os.path.join(output_dir, "analysis_timeseries.csv")
    fields = [
        "analysis_id", "date", "actual", "predicted",
        "predicted_lower", "predicted_upper", "point_effect", "cumulative_effect",
    ]
    with open(ts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for point in result.time_series:
            row = asdict(point)
            row["date"] = str(row["date"])
            writer.writerow(row)

    return summary_path, ts_path


def print_summary(result: AnalysisResult) -> None:
    """Print a concise, human-readable summary of the effect."""
    s = result.summary
    sig = "significant" if s.p_value < 0.05 else "not significant at p<0.05"
    logger.info("=" * 60)
    logger.info("RESULT")
    logger.info("=" * 60)
    logger.info("  Analysis type   : %s", s.analysis_type)
    logger.info("  Label           : %s", s.label)
    logger.info("  Backend used    : %s", s.backend)
    logger.info("  Intervention    : %s", s.intervention_date)
    logger.info("  Pre-period      : %s to %s", s.pre_period_start, s.pre_period_end)
    logger.info("  Post-period     : %s to %s", s.post_period_start, s.post_period_end)
    logger.info("  Cumulative effect: %.1f  [%.1f, %.1f] (90%% credible interval)",
                s.cumulative_effect, s.cumulative_effect_lower, s.cumulative_effect_upper)
    logger.info("  Relative lift    : %.1f%%", s.relative_effect_pct)
    logger.info("  p-value          : %.4f (%s)", s.p_value, sig)
    logger.info("  Prob. causal     : %.1f%%", s.prob_causal * 100)
    logger.info("=" * 60)


# =============================================================================
# Main
# =============================================================================

def _parse_intervention_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Causal Impact: BSTS counterfactual effect estimation from a CSV series."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on the bundled synthetic series with automated intervention discovery.",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help=f"Path to the input CSV. Default: {DEFAULT_INPUT_CSV}",
    )
    parser.add_argument(
        "--kpi",
        type=str,
        default=DEFAULT_KPI,
        choices=list(KPI_CONFIGS.keys()),
        help=f"KPI to analyse. Default: {DEFAULT_KPI}",
    )
    parser.add_argument(
        "--intervention-date",
        type=str,
        default=None,
        help="Intervention date (YYYY-MM-DD). If omitted, it is auto-detected.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write results. Default: {DEFAULT_OUTPUT_DIR}",
    )
    args = parser.parse_args()

    input_path = args.input or DEFAULT_INPUT_CSV
    if args.demo:
        input_path = DEFAULT_INPUT_CSV

    logger.info("=" * 60)
    logger.info("CAUSAL IMPACT (BSTS counterfactual)")
    logger.info("=" * 60)
    logger.info("Input            : %s", input_path)
    logger.info("KPI              : %s", args.kpi)
    logger.info("Intervention     : %s", args.intervention_date or "auto-detect")
    logger.info("Output dir       : %s", args.output_dir)

    # Step 1: load the series (warehouse read is stubbed to a CSV).
    series_df = load_series_csv(input_path)

    # Step 2: choose the intervention (supplied or auto-discovered) and build the spec.
    intervention_date = _parse_intervention_date(args.intervention_date)
    spec = prepare_spec(
        series_df=series_df,
        params=DETECTION_PARAMS,
        kpi_type=args.kpi,
        intervention_date=intervention_date,
    )

    if spec is None:
        logger.error("No analysis spec could be built. Nothing to do.")
        sys.exit(1)

    # Step 3: project to the KPI series and run the model.
    kpi_series = select_kpi_series(series_df, args.kpi)
    analysis_id = str(uuid.uuid4())
    result = run_single_analysis(
        spec=spec,
        series_df=kpi_series,
        analysis_id=analysis_id,
    )

    if result is None:
        logger.error("Analysis failed (all backends returned no result).")
        sys.exit(1)

    # Step 4: report and export (warehouse write is stubbed to local files).
    print_summary(result)
    summary_path, ts_path = export_result(result, args.output_dir)
    logger.info("Wrote summary   : %s", summary_path)
    logger.info("Wrote timeseries: %s", ts_path)


if __name__ == "__main__":
    main()
