[← Showreel](..)

# 📊 Bayesian MMM Runner

![Data science & ML](https://img.shields.io/badge/Data_science_%26_ML-3b82f6) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A containerisable batch job that fits a **Bayesian Marketing Mix Model** on
[Google Meridian](https://github.com/google/meridian) (TensorFlow-Probability /
NumPyro under the hood) and extracts the things a media team actually asks for:
per-channel **ROI and marginal ROI with credible intervals**, **adstock /
carryover**, **diminishing-returns response curves**, and a **fixed-budget
reallocation** across channels.

```
weekly media CSV ──▶ data_prep ──▶ Meridian InputData ──▶ MCMC fit
                                                              │
        results CSV/JSON ◀── export_results ◀── extract_results (Analyzer + Optimizer)
```

## The interesting part

The modelling itself is Meridian's; the value here is **productionising a
research library** so it can't silently produce wrong numbers. Three things in
`model_runner.py` are worth reading:

1. **Channels are mapped by name, never by position.** Meridian drops any channel
   with zero spend *before* fitting, so the fitted model's channel axis is a
   subset of your canonical channel list. If you read results back by positional
   index, every channel after the first dropped one is silently mislabelled - a
   channel's ROI gets attributed to its neighbour. The extractor builds an
   `active_order`/`active_pos` name→position map and pulls each channel's metrics
   **by name**, emitting genuine zero rows for channels that were dropped. The
   bundled sample data deliberately includes only 5 of 9 possible channels so
   this path is exercised on every demo run.

2. **Version-defensive result parsing.** Meridian has renamed its xarray
   variables and coordinates across releases (`roi` vs `ROI`, `pct_contribution`
   vs `pct_of_contribution`, a `metric` coord vs per-metric variables). The
   extractor resolves names case-insensitively with substring fallbacks and dumps
   the dataset shape when nothing matches, instead of returning zero-filled rows.

3. **Honest accuracy metrics.** Unweighted MAPE returns `inf` when any actual
   value is zero (division by zero). The metric extractor prefers `wMAPE`/`SMAPE`
   when present, skips non-finite candidates, and returns `NaN` (not `0.0`) on
   failure so a broken run can't masquerade as a perfect fit.

There's also a **profitability probability** computed straight from the raw ROI
posterior tensor (`P(ROI > threshold)`), and a `BudgetOptimizer` pass that
reallocates a fixed budget within ±30% per-channel bounds.

## Run it

```bash
pip install -r requirements.txt        # heavy: pulls in the Meridian / JAX stack
python main.py --demo                   # fast MCMC settings on the sample CSV
```

Results land in `./output/` (`channel_metrics.csv`, `response_curves.csv`,
`budget_optimization.csv`, `weekly_contributions.csv`, `model_run.json`).

Other modes:

```bash
python main.py --kpi revenue            # full-strength MCMC settings
python main.py --kpi conversions        # non-revenue KPI (profitability threshold 0)
python main.py --window h1              # fit only a named date window
```

> **Note:** `google-meridian` is a large dependency (TensorFlow-Probability /
> JAX). Installing it is the slow step, and MCMC fitting is CPU/RAM heavy even at
> `--demo` settings. The pipeline, the CLI and the result-extraction logic are
> the point of this sample; the fit will run wherever Meridian installs cleanly.

## What was stubbed for the demo

- **Data source** - the original read a data warehouse; here `data_prep.load_media_csv`
  reads a local CSV (`data/sample_media.csv`, generated deterministically). Point
  `MMM_DATA_CSV` (or `--csv`) at your own weekly data with the documented columns
  and nothing else changes.
- **Result sink** - the original wrote results back to the warehouse keyed on a
  run id; here `export_results` writes CSV/JSON to `./output/`.
- **Geo/market handling and the market-name normaliser** were removed - they were
  deployment-specific plumbing, not modelling.

Expected CSV columns: `week, channel, spend, impressions, kpi, brand_search_control`.

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
