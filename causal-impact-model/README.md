[← Showreel](..)

# 🧪 Causal Impact

![Data science & ML](https://img.shields.io/badge/Data_science_%26_ML-3b82f6) ![Python](https://img.shields.io/badge/Python-3776ab?logo=python&logoColor=white) ![offline demo](https://img.shields.io/badge/demo-offline-2ea44f)

A small, self-contained module that measures the causal effect of a marketing
intervention (for example a campaign launch or a media blackout) on a weekly
KPI, using a Bayesian structural time series (BSTS) counterfactual. It is
extracted from a larger production analytics system and rewritten to run
standalone from a CSV, with no cloud or warehouse dependencies.

## What is causal impact / BSTS counterfactual inference?

You cannot rerun history with the campaign turned off, so you cannot directly
observe what would have happened without it. Causal impact analysis answers the
counterfactual question by modelling it:

1. Fit a time series model on the **pre-intervention** period, when nothing
   special was happening.
2. Use that model to **forecast the counterfactual**: what the KPI would have
   done in the post period if the pre-period dynamics had simply continued.
3. The **causal effect** is the gap between what actually happened and that
   forecast, accumulated over the post period.

The model here is a **Bayesian structural time series** with a local linear
trend: a level and a slope that both evolve stochastically over time. Because
it is Bayesian, the forecast comes with a full predictive distribution, which
gives a **credible interval** on the effect and lets us report how likely the
effect is to be real rather than noise.

Reported metrics:

- **Cumulative effect** with a 90% credible interval (actual minus counterfactual, summed over the post period).
- **Relative lift**, the cumulative effect as a percentage of the counterfactual.
- **p-value**, an approximate probability that an effect this large could have arisen with no true effect.
- **Probability causal**, simply `1 - p_value`.

## Pipeline

```
CSV (date, spend, kpi)
        |
        v
 load + choose intervention date
   (auto-detect spend drop, or supplied on the CLI)
        |
        v
 build pre / post analysis window
        |
        v
 fit BSTS on pre-period  ->  forecast counterfactual into post-period
        |
        v
 effect = actual - counterfactual   (+ credible interval, relative lift, p-value)
        |
        v
 write ./output/analysis_summary.json  and  ./output/analysis_timeseries.csv
```

## The interesting part

**A three-backend resilience ladder.** BSTS is provided by a few Python
packages, each with different, sometimes fragile, native dependencies
(TensorFlow Probability in one case). Rather than depend on any single one, the
runner tries them in order and uses the first that works:

1. `tfcausalimpact` (TensorFlow Probability BSTS)
2. `pycausalimpact` (statsmodels-based CausalImpact)
3. a **from-scratch BSTS** built directly on `statsmodels` `UnobservedComponents`

**The from-scratch fallback is the point.** When neither CausalImpact package
is installed or importable, the module still does real causal inference. It
fits a local linear trend model (stochastic level and stochastic trend) on the
pre-period, forecasts the counterfactual with a credible interval into the post
period, computes the cumulative effect and relative lift, and derives an
approximate p-value from the share of the effect interval that sits on the
"no effect" side of zero. This path needs only `numpy`, `pandas`, and
`statsmodels`, so the analysis degrades gracefully instead of failing. See
`_run_statsmodels_fallback` in `model_runner.py`.

**Automated intervention discovery.** You do not always know the exact date to
test. If no intervention date is supplied, `data_prep.detect_interventions`
scans the spend series for a "media silence": a stretch of weeks where spend
falls below a configurable fraction of its trailing rolling average and stays
there for several consecutive weeks. The most pronounced such event becomes the
intervention date. If you already know the date, pass `--intervention-date` and
detection is skipped.

## Run it

```bash
pip install -r requirements.txt
python main.py --demo
```

`--demo` runs on the bundled synthetic series in `data/sample_series.csv`,
which has a clean spend drop partway through (a simulated media blackout) and a
matching step down in the KPI. The demo runs entirely on the from-scratch
statsmodels path, auto-detects the intervention, and writes results to
`./output/`.

Other ways to run it:

```bash
# Analyse your own weekly series
python main.py --input path/to/series.csv --kpi conversions

# Skip auto-detection and test a specific date
python main.py --input path/to/series.csv --intervention-date 2023-10-09
```

Input CSV format (one weekly row per line, dates on the week start):

```
date,spend,kpi
2023-01-02,99232.4,8061.4
2023-01-09,100044.9,8023.4
...
```

## What was stubbed

This is a portfolio extract of one module from a larger system. To make it
runnable on its own, the external dependencies were replaced with local
equivalents. The modelling code is unchanged in substance.

- **Warehouse read -> CSV loader.** The original pulled weekly, segmented media
  and KPI data from a cloud data warehouse. Here `data_prep.load_series_csv`
  reads a local CSV instead.
- **Warehouse write -> local files.** Results were written back to warehouse
  tables. Here `main.export_result` writes `analysis_summary.json` and
  `analysis_timeseries.csv` to `./output/`.
- **Cloud auth and job orchestration removed.** Credential handling, the
  scheduled cloud-job wrapper, and per-segment fan-out over many markets were
  dropped in favour of a single CLI run over one series.

## Files

| File | Purpose |
|---|---|
| `config.py` | KPI definitions, detection thresholds, default paths. |
| `data_prep.py` | CSV loader, automated intervention discovery, spec construction. |
| `model_runner.py` | The three-backend BSTS ladder and result assembly. |
| `main.py` | CLI entry point, `--demo`, and local export. |
| `data/sample_series.csv` | Deterministic synthetic weekly series for the demo. |

---

MIT · Part of [Showreel](..), twelve standalone engineering projects.
