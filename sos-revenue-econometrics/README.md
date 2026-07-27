[← Showreel](..)

# 📈 Spend → Demand → Revenue Econometrics

![Data science & ML](https://img.shields.io/badge/Data_science_%26_ML-3b82f6) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A standalone Python module that answers one question: does a brand-demand
signal (call it `brand_search`) mediate the path from marketing spend to
revenue, and with what time lag?

It works on a weekly panel of markets. For each market it estimates how a
shock to spend propagates first into demand and then into revenue, and how
many weeks that whole chain takes.

## What the module does

For every market in the input panel it runs, all on `statsmodels`:

1. **Granger causality tests** in three directions, at lags 1 to 12:
   - `total_spend -> brand_search`
   - `brand_search -> revenue`
   - `total_spend -> revenue`
2. **A Vector Autoregression (VAR)** on `[total_spend, brand_search, revenue]`,
   with the lag order chosen by AIC.
3. **Impulse Response Functions (IRFs)** with Monte-Carlo bootstrap confidence
   bands, tracing the response of one variable to a one-standard-deviation
   shock in another over a 24-week horizon.
4. **Per-channel VARs** (one per spend channel) so you can see which channel
   moves demand and revenue most.
5. **A derived lag structure** per variable pair: the optimal lag, the
   peak-response week, the cumulative effect, and the half-life.

Everything is z-score standardised before the VAR so the coefficients and
impulse responses are comparable across markets and variables.

## The interesting part

- **Granger causality across three directions and twelve lags.** Rather than a
  single "does spend move revenue" test, it separates the mediated path
  (spend into demand, demand into revenue) from the direct path (spend into
  revenue), at every lag from 1 to 12 weeks.
- **VAR with AIC lag selection.** The lag order is not hard-coded. The module
  runs `select_order` and fits at the AIC-optimal lag, bounded by the data
  length so short panels stay well-posed.
- **Impulse responses with bootstrap confidence intervals.** IRFs use a
  Monte-Carlo error band (`errband_mc`). If the bootstrap fails (which can
  happen on thin or near-collinear data), it degrades to an asymptotic-style
  band around the point estimate rather than dropping the result.
- **Half-life extraction, signed.** The half-life is the number of weeks to
  reach 50% of the cumulative impulse effect. It is computed correctly for
  both positive and negative cumulative effects, and returns 0 when the
  cumulative effect is effectively nil.
- **Zero-variance graceful degradation.** If a market has no demand signal
  (a flat `brand_search` column), the 3-variable VAR would hit a singular
  covariance matrix. The module detects the zero-variance column up front and
  falls back to a 2-variable `[total_spend, revenue]` VAR, and it also guards
  the singular-matrix `LinAlgError` at fit time. One market in the sample data
  is deliberately built this way so you can watch the fall-back fire.

## Run it

```bash
pip install -r requirements.txt
python main.py --demo
```

`--demo` regenerates the deterministic sample panel first, then runs every
market. Without `--demo` it reuses the existing sample CSV. You can also point
it at your own weekly panel or restrict the markets:

```bash
python main.py --csv path/to/your_weekly_panel.csv
python main.py --market market_alpha,market_beta
```

Results are written to `./output/`:

- `granger_tests.csv` one row per market, direction, and lag
- `impulse_responses.csv` one row per market, impulse, response, and horizon week
- `lag_structure.csv` optimal lag, peak week, cumulative effect, half-life
- `model_run.json` run metadata and a per-market summary

### Input format

A weekly CSV panel with one row per market per week:

| column | meaning |
|---|---|
| `market` | market identifier |
| `week_start` | week start date |
| `total_spend` | total marketing spend that week |
| `search_spend`, `social_spend`, `display_spend`, `video_spend` | per-channel spend |
| `brand_search` | the brand-demand signal (the hypothesised mediator) |
| `revenue` | revenue that week |

`data/sample_market_weekly.csv` is a generated example with a believable
lagged relationship (spend leads demand by 2 to 3 weeks, demand leads revenue
by 1 to 2 weeks), so the Granger tests and IRFs show real signal.

## What was stubbed

This is an extract from a larger production pipeline, reworked to run on its
own with no external services:

- **Data warehouse to CSV.** The original loader queried a cloud data
  warehouse, mapped raw channels, and aggregated to weekly panels. That is
  replaced by a deterministic synthetic CSV generator in `data_prep.py`
  (`generate_sample_csv`) plus a plain CSV reader. Swap in your own loader and
  the model code is unchanged.
- **Results to local files.** The original wrote results to warehouse tables.
  This version writes CSV and JSON to `./output/`.
- **Credentials and cloud config removed.** No project IDs, service accounts,
  or environment secrets are needed to run it.

The econometrics (Granger tests, VAR, IRF with bootstrap bands, lag-structure
extraction, and the zero-variance fall-back) are kept faithfully from the
original.

## Files

```
config.py         paths, column definitions, model hyperparameters
data_prep.py      synthetic CSV generator, loader, z-score standardisation
model_runner.py   Granger + VAR + IRF + lag structure (the core)
main.py           CLI, results export, summary
requirements.txt  numpy, pandas, scipy, statsmodels
data/             sample_market_weekly.csv
output/           results land here
```

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
