"""
Bayesian MMM runner - CLI entry point.

Pipeline: load weekly media CSV -> build Meridian InputData -> fit via MCMC ->
extract ROI / response curves / budget optimisation -> write results locally.

Usage:
    python main.py --demo                 # fast fit on the bundled synthetic CSV
    python main.py --kpi revenue          # full-strength settings
    python main.py --kpi conversions --window h1

In a container this is the Job entry point; scheduler-supplied flags append after
`python main.py`, which is why an ENTRYPOINT (not CMD) is used in the Dockerfile.
"""


# The demos print box-drawing characters and arrows. A Windows console defaults
# to cp1252, which cannot encode them, so an unguarded print crashes the demo on
# a clean Windows machine. No-op on Linux and macOS.
import sys as _sys
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
import argparse
import logging
import sys

from config import (
    ALL_KPIS,
    DATA_CSV_PATH,
    DEFAULT_KPI,
    DEMO_PARAMS,
    KPI_CONFIGS,
    MODEL_PARAMS,
    SEASONALITY_WINDOWS,
)
from data_prep import prepare_data
from export_results import export_results
from model_runner import run_model


def _stable_run_id(kpi_type: str, window: str) -> str:
    """Deterministic run id from (kpi, window).

    Deterministic on purpose: in a sharded deployment every task shares one
    logical run id (e.g. via uuid5(execution, kpi)) so all shards write into the
    same logical run. Here we keep it simple and fully reproducible.
    """
    return f"run_{kpi_type}_{window}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bayesian Marketing Mix Model runner")
    parser.add_argument("--kpi", default=DEFAULT_KPI, choices=sorted(KPI_CONFIGS.keys()))
    parser.add_argument("--all-kpis", action="store_true", help="Run every KPI in ALL_KPIS")
    parser.add_argument("--window", default="full", choices=sorted(SEASONALITY_WINDOWS.keys()))
    parser.add_argument("--csv", default=DATA_CSV_PATH, help="Path to the weekly media CSV")
    parser.add_argument("--demo", action="store_true", help="Fast/small MCMC settings for a quick run")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("main")

    params = DEMO_PARAMS if args.demo else MODEL_PARAMS
    # A short window has fewer weeks, so relax the validation floor for it.
    min_weeks = 26 if args.window != "full" else 52
    kpis = ALL_KPIS if args.all_kpis else [args.kpi]

    for kpi_type in kpis:
        log.info("Running MMM for KPI=%s, window=%s, demo=%s", kpi_type, args.window, args.demo)
        try:
            input_data, weekly_df, weeks = prepare_data(
                kpi_type, params, csv_path=args.csv, min_weeks=min_weeks,
            )
            results = run_model(input_data, weekly_df, weeks, kpi_type, params)
            export_results(results, kpi_type, _stable_run_id(kpi_type, args.window))
            log.info(
                "DONE KPI=%s: R^2=%.3f, MAPE=%.3f, %d channels",
                kpi_type, results.r_squared, results.mape, len(results.channel_metrics),
            )
        except Exception as exc:  # noqa: BLE001 - top-level guard for a batch job
            log.error("Run failed for KPI=%s: %s", kpi_type, exc, exc_info=True)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
