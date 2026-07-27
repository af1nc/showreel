"""
Write model results to local CSV/JSON files.

In production this is where results would be written back to a data warehouse
(idempotently, keyed on a run id). For the standalone demo we just write CSV +
a run-summary JSON into an output directory so you can inspect them.
"""

import csv
import json
import logging
import os
from dataclasses import asdict
from typing import List

from config import OUTPUT_DIR
from model_runner import ModelResults

logger = logging.getLogger(__name__)


def _write_csv(path: str, rows: List[dict]) -> None:
    if not rows:
        logger.warning("No rows to write for %s", os.path.basename(path))
        # Still create an empty file so the absence is explicit.
        open(path, "w").close()
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows -> %s", len(rows), os.path.basename(path))


def export_results(
    results: ModelResults,
    kpi_type: str,
    run_id: str,
    output_dir: str = OUTPUT_DIR,
) -> None:
    """Write all result tables plus a run-summary JSON to ``output_dir``."""
    os.makedirs(output_dir, exist_ok=True)

    _write_csv(
        os.path.join(output_dir, "channel_metrics.csv"),
        [asdict(m) for m in results.channel_metrics],
    )
    _write_csv(
        os.path.join(output_dir, "response_curves.csv"),
        [asdict(p) for p in results.response_curves],
    )
    _write_csv(
        os.path.join(output_dir, "budget_optimization.csv"),
        [asdict(b) for b in results.budget_optimization],
    )
    _write_csv(
        os.path.join(output_dir, "weekly_contributions.csv"),
        [asdict(w) for w in results.weekly_contributions],
    )

    summary = {
        "run_id": run_id,
        "kpi_type": kpi_type,
        "r_squared": results.r_squared,
        "mape": results.mape,
        "n_channels": len(results.channel_metrics),
        "n_response_curve_points": len(results.response_curves),
        "n_budget_rows": len(results.budget_optimization),
        "n_weekly_rows": len(results.weekly_contributions),
    }
    with open(os.path.join(output_dir, "model_run.json"), "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Wrote run summary -> model_run.json  (%s)", summary)
