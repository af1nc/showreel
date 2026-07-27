"""
Standalone runner for the spend -> brand-demand -> revenue lag model.

Models the causal pipeline: marketing spend -> a brand-demand signal
(brand_search) -> revenue, and quantifies the lag structure using Granger
causality tests and Vector Autoregression (VAR) impulse response functions.

Core question: does a brand-demand signal mediate the path from marketing
spend to revenue, and with what time lag? When spend rises, brand_search
tends to rise after X weeks; when brand_search rises, revenue tends to
follow after Y weeks. The end-to-end pipeline is roughly X+Y weeks.

Usage:
  python main.py --demo               # generate sample data, run every market
  python main.py                      # run against an existing sample CSV
  python main.py --csv path/to.csv    # run against your own weekly panel
  python main.py --market market_alpha,market_beta   # run specific markets
"""

import argparse
import dataclasses
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from config import (
    MAX_LAG_WEEKS,
    MIN_WEEKS,
    OUTPUT_DIR,
    SAMPLE_CSV,
)
from data_prep import generate_sample_csv, prepare_data
from model_runner import MarketResults, run_all_markets

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("spend-brand-revenue")


# =============================================================================
# Results export (local files: CSV + JSON)
# =============================================================================

def _json_default(o):
    """Coerce numpy scalars (int64/float64) to native types for JSON."""
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def export_results(
    all_results: Dict[str, MarketResults],
    run_id: str,
    run_timestamp: str,
    status: str,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """
    Write results to local files:
      granger_tests.csv     one row per (market, direction, lag)
      impulse_responses.csv one row per (market, impulse, response, horizon)
      lag_structure.csv     one row per (market, variable_pair)
      model_run.json        run metadata + per-market summary
    """
    import csv

    output_dir.mkdir(parents=True, exist_ok=True)

    granger_rows = [
        dataclasses.asdict(g)
        for r in all_results.values() for g in r.granger
    ]
    irf_rows = [
        dataclasses.asdict(ir)
        for r in all_results.values() for ir in r.impulse_responses
    ]
    lag_rows = [
        dataclasses.asdict(ls)
        for r in all_results.values() for ls in r.lag_structure
    ]

    def _write_csv(name: str, rows: list, header: list) -> None:
        path = output_dir / name
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        logger.info("Wrote %d rows -> %s", len(rows), path)

    _write_csv(
        "granger_tests.csv", granger_rows,
        ["market", "direction", "lag_weeks", "f_statistic", "p_value", "significant"],
    )
    _write_csv(
        "impulse_responses.csv", irf_rows,
        ["market", "impulse_variable", "response_variable", "horizon_weeks",
         "response", "response_lower", "response_upper"],
    )
    _write_csv(
        "lag_structure.csv", lag_rows,
        ["market", "variable_pair", "optimal_lag_weeks", "peak_response_week",
         "total_cumulative_effect", "half_life_weeks"],
    )

    # Run metadata + per-market summary.
    run_meta = {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "status": status,
        "max_lag_weeks": MAX_LAG_WEEKS,
        "min_weeks": MIN_WEEKS,
        "n_markets": len(all_results),
        "markets": {
            m: {
                "error": r.error,
                "var_lag_order": r.var_lag_order,
                "var_aic": r.var_aic,
                "n_granger": len(r.granger),
                "n_impulse_responses": len(r.impulse_responses),
                "n_lag_structure": len(r.lag_structure),
                "lag_structure": [dataclasses.asdict(ls) for ls in r.lag_structure],
            }
            for m, r in sorted(all_results.items())
        },
    }
    meta_path = output_dir / "model_run.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(run_meta, f, indent=2, default=_json_default)
    logger.info("Wrote run metadata -> %s", meta_path)


# =============================================================================
# Human-readable summary
# =============================================================================

def _print_summary(all_results: Dict[str, MarketResults]) -> None:
    """Print a human-readable summary of key findings across markets."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("KEY FINDINGS SUMMARY")
    logger.info("=" * 60)

    for market, result in sorted(all_results.items()):
        if result.error:
            logger.info("[%s] FAILED: %s", market, result.error)
            continue

        spend_to_signal = next(
            (ls for ls in result.lag_structure
             if ls.variable_pair == "spend->brand_search"),
            None,
        )
        signal_to_rev = next(
            (ls for ls in result.lag_structure
             if ls.variable_pair == "brand_search->revenue"),
            None,
        )
        spend_to_rev = next(
            (ls for ls in result.lag_structure
             if ls.variable_pair == "spend->revenue"),
            None,
        )

        # Check Granger significance per direction.
        granger_sig = {}
        for direction in ["spend_to_brand_search", "brand_search_to_revenue", "spend_to_revenue"]:
            dir_results = [g for g in result.granger if g.direction == direction]
            any_sig = any(g.significant for g in dir_results)
            min_p = min((g.p_value for g in dir_results), default=1.0)
            granger_sig[direction] = (any_sig, min_p)

        logger.info("")
        logger.info(
            "[%s] VAR lag order: %d (AIC: %.2f)",
            market, result.var_lag_order, result.var_aic,
        )

        if spend_to_signal:
            sig_str = "YES" if granger_sig.get("spend_to_brand_search", (False,))[0] else "no"
            logger.info(
                "[%s]   Spend -> brand_search: peak at week %d, half-life %.1f weeks "
                "(Granger significant: %s, min p=%.4f)",
                market,
                spend_to_signal.peak_response_week,
                spend_to_signal.half_life_weeks,
                sig_str,
                granger_sig.get("spend_to_brand_search", (False, 1.0))[1],
            )

        if signal_to_rev:
            sig_str = "YES" if granger_sig.get("brand_search_to_revenue", (False,))[0] else "no"
            logger.info(
                "[%s]   brand_search -> Revenue: peak at week %d, half-life %.1f weeks "
                "(Granger significant: %s, min p=%.4f)",
                market,
                signal_to_rev.peak_response_week,
                signal_to_rev.half_life_weeks,
                sig_str,
                granger_sig.get("brand_search_to_revenue", (False, 1.0))[1],
            )

        if spend_to_signal and signal_to_rev:
            total_pipeline = (
                spend_to_signal.peak_response_week + signal_to_rev.peak_response_week
            )
            logger.info(
                "[%s]   TOTAL PIPELINE: ~%d weeks from spend to revenue "
                "(spend->signal: %d wks + signal->revenue: %d wks)",
                market, total_pipeline,
                spend_to_signal.peak_response_week,
                signal_to_rev.peak_response_week,
            )

        if spend_to_rev:
            sig_str = "YES" if granger_sig.get("spend_to_revenue", (False,))[0] else "no"
            logger.info(
                "[%s]   Direct spend -> Revenue: peak at week %d "
                "(Granger significant: %s, min p=%.4f)",
                market,
                spend_to_rev.peak_response_week,
                sig_str,
                granger_sig.get("spend_to_revenue", (False, 1.0))[1],
            )


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spend -> brand-demand -> revenue lag model (standalone)."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Regenerate the deterministic sample CSV before running.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=str(SAMPLE_CSV),
        help="Path to a weekly panel CSV (defaults to the bundled sample).",
    )
    parser.add_argument(
        "--market",
        type=str,
        default=None,
        help="Comma-separated market names to run (default: all markets).",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if args.demo:
        logger.info("Demo mode: regenerating deterministic sample CSV.")
        generate_sample_csv(csv_path)

    target_markets = None
    if args.market:
        target_markets = [m.strip() for m in args.market.split(",") if m.strip()]

    run_id = str(uuid.uuid4())
    run_timestamp = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("SPEND -> BRAND-DEMAND -> REVENUE LAG MODEL")
    logger.info("=" * 60)
    logger.info("Run ID: %s", run_id)
    logger.info("Timestamp: %s", run_timestamp)
    logger.info("Input CSV: %s", csv_path)
    logger.info("Max lag: %d weeks", MAX_LAG_WEEKS)
    logger.info("Min data: %d weeks", MIN_WEEKS)

    start_time = time.time()
    status = "success"

    try:
        # --- Step 1: Data preparation (load + standardise) ---
        logger.info("Preparing data...")
        _raw, std_market_data, _stats = prepare_data(csv_path)

        # Optional filter to specific markets.
        if target_markets:
            std_market_data = {
                m: df for m, df in std_market_data.items() if m in target_markets
            }
            missing = [m for m in target_markets if m not in std_market_data]
            if missing:
                logger.warning("Requested markets not found in data: %s", missing)

        if not std_market_data:
            logger.error("No markets to model after filtering. Exiting.")
            sys.exit(1)

        logger.info(
            "Ready to model %d markets: %s",
            len(std_market_data), sorted(std_market_data.keys()),
        )

        # --- Step 2: Run models ---
        logger.info("Starting model runs...")
        all_results = run_all_markets(std_market_data)

        n_markets = len(all_results)
        n_success = sum(1 for r in all_results.values() if r.error is None)
        n_failed = n_markets - n_success

        if n_success == 0:
            status = "failed: all markets failed"
            logger.error("ALL markets failed, no results to export.")
        elif n_failed > 0:
            status = f"partial: {n_success}/{n_markets} succeeded"
            logger.warning(
                "%d/%d markets failed: %s",
                n_failed, n_markets,
                [m for m, r in all_results.items() if r.error is not None],
            )

        # --- Step 3: Export to local files ---
        logger.info("Exporting results to %s ...", OUTPUT_DIR)
        export_results(all_results, run_id, run_timestamp, status)

        # --- Step 4: Summary ---
        _print_summary(all_results)

    except Exception as e:
        status = f"failed: {str(e)[:200]}"
        logger.error("MODEL RUN FAILED: %s", e, exc_info=True)
        sys.exit(1)

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("RUN COMPLETE")
    logger.info("Status: %s", status)
    logger.info("Duration: %.1f seconds", elapsed)
    logger.info("Run ID: %s", run_id)
    logger.info("Results in: %s", OUTPUT_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
