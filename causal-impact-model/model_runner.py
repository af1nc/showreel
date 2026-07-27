"""
Causal Impact model runner.

For an AnalysisSpec, this module builds a weekly time series, fits a Bayesian
structural time series (BSTS) model on the pre-intervention period, forecasts
the counterfactual into the post period, and extracts the causal effect:
cumulative effect with a credible interval, relative percent lift, an
approximate p-value, and a probability that the effect is causal.

Three backends are tried in order (a resilience ladder):
  1. tfcausalimpact   (TensorFlow Probability BSTS)
  2. pycausalimpact   (statsmodels-based CausalImpact)
  3. a from-scratch BSTS built on statsmodels UnobservedComponents

The from-scratch fallback is the important part: it runs with only statsmodels
installed, so the pipeline still produces a counterfactual and an effect
estimate even when neither CausalImpact package is available.
"""

import logging
import warnings
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

import pandas as pd

from config import CREDIBLE_INTERVAL_ALPHA, KPI_CONFIGS
from data_prep import AnalysisSpec

logger = logging.getLogger(__name__)

# Suppress noisy TF/JAX warnings if the optional backends are installed.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="tensorflow")


# =============================================================================
# Result Containers
# =============================================================================

@dataclass
class AnalysisSummary:
    """Summary statistics from a single Causal Impact analysis."""
    analysis_id: str
    analysis_type: str
    label: str
    intervention_date: date
    pre_period_start: date
    pre_period_end: date
    post_period_start: date
    post_period_end: date
    kpi_type: str
    backend: str
    cumulative_effect: float
    cumulative_effect_lower: float
    cumulative_effect_upper: float
    relative_effect_pct: float
    p_value: float
    prob_causal: float


@dataclass
class TimeSeriesPoint:
    """A single time-series point from a Causal Impact analysis."""
    analysis_id: str
    date: date
    actual: float
    predicted: float
    predicted_lower: float
    predicted_upper: float
    point_effect: float
    cumulative_effect: float


@dataclass
class AnalysisResult:
    """Complete result for a single analysis."""
    summary: AnalysisSummary
    time_series: List[TimeSeriesPoint]


# =============================================================================
# Time Series Construction
# =============================================================================

def build_time_series(
    spec: AnalysisSpec,
    series_df: pd.DataFrame,
) -> Optional[pd.DataFrame]:
    """
    Build the weekly time series for the given AnalysisSpec.

    Expects series_df with columns: date, y, spend. Returns a DataFrame
    indexed by date with the response column "y" (and "spend" as a covariate),
    covering both pre and post periods. Returns None if there is not enough
    data to fit a model.
    """
    kpi_config = KPI_CONFIGS[spec.kpi_type]

    ts = series_df.copy()
    ts["date"] = pd.to_datetime(ts["date"]).dt.date

    # Filter to the analysis window (pre_period_start to post_period_end).
    ts = ts[
        (ts["date"] >= spec.pre_period_start)
        & (ts["date"] <= spec.post_period_end)
    ].copy()

    ts = ts.sort_values("date").reset_index(drop=True)

    if len(ts) < 10:
        logger.warning(
            "Only %d data points for %s [%s], skipping (need >= 10)",
            len(ts), spec.label, spec.kpi_type,
        )
        return None

    # Keep the response and, when present, spend as a covariate. The
    # from-scratch fallback uses only "y"; the CausalImpact backends can use
    # "spend" as a control series when it is informative.
    keep_cols = ["date", "y"]
    if "spend" in ts.columns:
        ts["spend"] = ts["spend"].fillna(0)
        keep_cols.append("spend")

    ts = ts[keep_cols].set_index("date")

    logger.debug("Built time series for %s (KPI %s): %d rows",
                 spec.label, kpi_config.name, len(ts))
    return ts


# =============================================================================
# Causal Impact Execution (multi-backend ladder)
# =============================================================================

def _run_tfcausalimpact(
    ts: pd.DataFrame,
    pre_period: Tuple[str, str],
    post_period: Tuple[str, str],
) -> Optional[dict]:
    """
    Run CausalImpact using tfcausalimpact (TensorFlow Probability BSTS).
    Returns a dict with summary metrics and a pointwise DataFrame, or None on failure.
    """
    try:
        from causalimpact import CausalImpact  # type: ignore

        # tfcausalimpact expects a DatetimeIndex.
        df = ts.copy()
        df.index = pd.to_datetime(df.index)

        ci = CausalImpact(
            data=df,
            pre_period=pre_period,
            post_period=post_period,
            prior_level_sd=None,  # Auto
        )

        summary = ci.summary_data
        inferences = ci.inferences

        # Extract summary metrics (column names vary across versions).
        cumulative = float(inferences["post_cum_y"].iloc[-1] - inferences["post_cum_pred"].iloc[-1]) \
            if "post_cum_y" in inferences.columns else float(summary.loc["cumulative", "abs_effect"])
        cumulative_lower = float(summary.loc["cumulative", "abs_effect_lower"]) \
            if "abs_effect_lower" in summary.columns else 0.0
        cumulative_upper = float(summary.loc["cumulative", "abs_effect_upper"]) \
            if "abs_effect_upper" in summary.columns else 0.0
        relative_pct = float(summary.loc["cumulative", "rel_effect"]) * 100 \
            if "rel_effect" in summary.columns else 0.0
        p_value = float(ci.p_value) if hasattr(ci, "p_value") else 0.0

        return {
            "cumulative_effect": cumulative,
            "cumulative_effect_lower": cumulative_lower,
            "cumulative_effect_upper": cumulative_upper,
            "relative_effect_pct": relative_pct,
            "p_value": p_value,
            "inferences": inferences,
            "backend": "tfcausalimpact",
        }

    except ImportError:
        logger.debug("tfcausalimpact not available.")
        return None
    except Exception as e:
        logger.warning("tfcausalimpact failed: %s", e)
        return None


def _run_pycausalimpact(
    ts: pd.DataFrame,
    pre_period: Tuple[str, str],
    post_period: Tuple[str, str],
) -> Optional[dict]:
    """
    Run CausalImpact using pycausalimpact (statsmodels-based).
    Returns a dict with summary metrics and a pointwise DataFrame, or None on failure.
    """
    try:
        from causalimpact import CausalImpact  # type: ignore

        df = ts.copy()
        df.index = pd.to_datetime(df.index)

        ci = CausalImpact(
            data=df,
            pre_period=[pd.Timestamp(pre_period[0]), pd.Timestamp(pre_period[1])],
            post_period=[pd.Timestamp(post_period[0]), pd.Timestamp(post_period[1])],
        )

        inferences = ci.inferences if hasattr(ci, "inferences") else None
        if inferences is None or inferences.empty:
            logger.warning("pycausalimpact returned no inferences.")
            return None

        summary_data = ci.summary_data if hasattr(ci, "summary_data") else None

        if summary_data is not None and len(summary_data) > 0:
            cum_row = summary_data.loc["cumulative"] if "cumulative" in summary_data.index else summary_data.iloc[-1]
            cumulative = float(cum_row.get("abs_effect", 0))
            cumulative_lower = float(cum_row.get("abs_effect_lower", 0))
            cumulative_upper = float(cum_row.get("abs_effect_upper", 0))
            relative_pct = float(cum_row.get("rel_effect", 0)) * 100
        else:
            # Compute from inferences.
            post_mask = inferences.index >= pd.Timestamp(post_period[0])
            post_inferences = inferences[post_mask]
            if "point_effect" in post_inferences.columns:
                cumulative = float(post_inferences["point_effect"].sum())
            else:
                cumulative = 0.0
            cumulative_lower = 0.0
            cumulative_upper = 0.0
            relative_pct = 0.0

        p_value = float(ci.p_value) if hasattr(ci, "p_value") else 0.0

        return {
            "cumulative_effect": cumulative,
            "cumulative_effect_lower": cumulative_lower,
            "cumulative_effect_upper": cumulative_upper,
            "relative_effect_pct": relative_pct,
            "p_value": p_value,
            "inferences": inferences,
            "backend": "pycausalimpact",
        }

    except ImportError:
        logger.debug("pycausalimpact not available.")
        return None
    except Exception as e:
        logger.warning("pycausalimpact failed: %s", e)
        return None


def _run_statsmodels_fallback(
    ts: pd.DataFrame,
    pre_period: Tuple[str, str],
    post_period: Tuple[str, str],
) -> Optional[dict]:
    """
    From-scratch BSTS fallback using statsmodels UnobservedComponents.

    Fits a local linear trend model (stochastic level + stochastic trend) on
    the pre-period, forecasts the counterfactual into the post-period, and
    computes the causal impact as actual minus predicted. A rough p-value is
    derived from the forecast credible interval. This path runs with only
    statsmodels, numpy, and pandas installed.
    """
    try:
        from statsmodels.tsa.statespace.structural import UnobservedComponents

        df = ts[["y"]].copy()
        df.index = pd.to_datetime(df.index)
        df = df.asfreq("W-MON")  # Ensure a regular weekly frequency.
        df["y"] = df["y"].interpolate(method="linear").fillna(0)

        pre_start = pd.Timestamp(pre_period[0])
        pre_end = pd.Timestamp(pre_period[1])
        post_start = pd.Timestamp(post_period[0])
        post_end = pd.Timestamp(post_period[1])

        # Split into pre / post.
        pre_data = df.loc[pre_start:pre_end]
        post_data = df.loc[post_start:post_end]

        if len(pre_data) < 10:
            logger.warning("Statsmodels fallback: only %d pre-period points", len(pre_data))
            return None

        # Fit a local linear trend model on the pre-period. Both the level and
        # the trend are stochastic, which is the defining structure of a BSTS
        # local linear trend component.
        model = UnobservedComponents(
            pre_data["y"],
            level="local linear trend",
            stochastic_level=True,
            stochastic_trend=True,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit_result = model.fit(disp=False, maxiter=500)

        # Forecast the counterfactual into the post-period.
        n_forecast = len(post_data)
        if n_forecast == 0:
            logger.warning("Statsmodels fallback: no post-period data")
            return None

        forecast = fit_result.get_forecast(steps=n_forecast)
        predicted_mean = forecast.predicted_mean
        conf_int = forecast.conf_int(alpha=CREDIBLE_INTERVAL_ALPHA)

        # Build the full inferences DataFrame.
        # Pre-period: in-sample fitted values.
        pre_fitted = fit_result.fittedvalues
        pre_conf = fit_result.get_prediction().conf_int(alpha=CREDIBLE_INTERVAL_ALPHA)

        all_dates = df.index
        inferences = pd.DataFrame(index=all_dates)
        inferences["actual"] = df["y"]

        # Pre-period predictions.
        inferences.loc[pre_data.index, "predicted"] = pre_fitted.values
        if hasattr(pre_conf, "values"):
            inferences.loc[pre_data.index, "predicted_lower"] = pre_conf.iloc[:, 0].values
            inferences.loc[pre_data.index, "predicted_upper"] = pre_conf.iloc[:, 1].values
        else:
            inferences.loc[pre_data.index, "predicted_lower"] = pre_fitted.values
            inferences.loc[pre_data.index, "predicted_upper"] = pre_fitted.values

        # Post-period predictions (the counterfactual).
        post_dates = post_data.index[:n_forecast]
        inferences.loc[post_dates, "predicted"] = predicted_mean.values[:len(post_dates)]
        inferences.loc[post_dates, "predicted_lower"] = conf_int.iloc[:len(post_dates), 0].values
        inferences.loc[post_dates, "predicted_upper"] = conf_int.iloc[:len(post_dates), 1].values

        # Fill any gaps.
        inferences["predicted"] = inferences["predicted"].fillna(inferences["actual"])
        inferences["predicted_lower"] = inferences["predicted_lower"].fillna(inferences["predicted"])
        inferences["predicted_upper"] = inferences["predicted_upper"].fillna(inferences["predicted"])

        # Pointwise effects.
        inferences["point_effect"] = inferences["actual"] - inferences["predicted"]
        inferences["cumulative_effect"] = 0.0

        # Cumulative effect accumulates only through the post-period.
        post_mask = inferences.index >= post_start
        post_effects = inferences.loc[post_mask, "point_effect"]
        inferences.loc[post_mask, "cumulative_effect"] = post_effects.cumsum()

        # Summary metrics.
        cumulative = float(inferences.loc[post_mask, "point_effect"].sum())
        predicted_sum = float(inferences.loc[post_mask, "predicted"].sum())
        relative_pct = (cumulative / predicted_sum * 100) if predicted_sum != 0 else 0.0

        # Approximate credible bounds on the cumulative effect by summing the
        # per-point counterfactual bounds against the observed actuals.
        post_actual_sum = float(inferences.loc[post_mask, "actual"].sum())
        post_upper_sum = float(inferences.loc[post_mask, "predicted_upper"].sum())
        post_lower_sum = float(inferences.loc[post_mask, "predicted_lower"].sum())
        cumulative_lower = post_actual_sum - post_upper_sum
        cumulative_upper = post_actual_sum - post_lower_sum

        # Rough p-value: the share of the effect interval that sits on the
        # "no effect" side of zero.
        if cumulative < 0:
            # Negative effect: p-value is the probability that the true effect >= 0.
            p_value = max(0.0, min(1.0,
                cumulative_upper / (cumulative_upper - cumulative_lower)
            )) if (cumulative_upper - cumulative_lower) != 0 else 0.5
        else:
            # Positive effect: p-value is the probability that the true effect <= 0.
            p_value = max(0.0, min(1.0,
                -cumulative_lower / (cumulative_upper - cumulative_lower)
            )) if (cumulative_upper - cumulative_lower) != 0 else 0.5

        return {
            "cumulative_effect": cumulative,
            "cumulative_effect_lower": cumulative_lower,
            "cumulative_effect_upper": cumulative_upper,
            "relative_effect_pct": relative_pct,
            "p_value": p_value,
            "inferences": inferences,
            "backend": "statsmodels_fallback",
        }

    except Exception as e:
        logger.error("Statsmodels fallback failed: %s", e, exc_info=True)
        return None


# =============================================================================
# Core Runner
# =============================================================================

def run_single_analysis(
    spec: AnalysisSpec,
    series_df: pd.DataFrame,
    analysis_id: str,
) -> Optional[AnalysisResult]:
    """
    Run a single Causal Impact analysis for the given spec.

    Tries three backends in order:
      1. tfcausalimpact (TensorFlow Probability BSTS)
      2. pycausalimpact (statsmodels-based)
      3. from-scratch statsmodels UnobservedComponents fallback

    Returns an AnalysisResult, or None if all backends fail.
    """
    logger.info("Running analysis: %s", spec.label)
    logger.info(
        "  Pre-period: %s to %s | Post-period: %s to %s | KPI: %s",
        spec.pre_period_start, spec.pre_period_end,
        spec.post_period_start, spec.post_period_end,
        spec.kpi_type,
    )

    # Step 1: build the time series.
    ts = build_time_series(spec, series_df)
    if ts is None:
        return None

    logger.info("  Time series: %d data points, y range [%.1f, %.1f]",
                len(ts), ts["y"].min(), ts["y"].max())

    # Step 2: define periods as ISO date strings.
    pre_period = (str(spec.pre_period_start), str(spec.pre_period_end))
    post_period = (str(spec.post_period_start), str(spec.post_period_end))

    # Step 3: try the backends in order.
    result_dict = _run_tfcausalimpact(ts, pre_period, post_period)
    if result_dict is None:
        result_dict = _run_pycausalimpact(ts, pre_period, post_period)
    if result_dict is None:
        result_dict = _run_statsmodels_fallback(ts, pre_period, post_period)

    if result_dict is None:
        logger.error("  All backends failed for: %s", spec.label)
        return None

    backend = result_dict["backend"]
    logger.info("  Backend used: %s", backend)
    logger.info(
        "  Cumulative effect: %.2f [%.2f, %.2f], relative: %.1f%%, p-value: %.4f",
        result_dict["cumulative_effect"],
        result_dict["cumulative_effect_lower"],
        result_dict["cumulative_effect_upper"],
        result_dict["relative_effect_pct"],
        result_dict["p_value"],
    )

    # Step 4: build the result objects.
    prob_causal = 1.0 - result_dict["p_value"]

    summary = AnalysisSummary(
        analysis_id=analysis_id,
        analysis_type=spec.analysis_type,
        label=spec.label,
        intervention_date=spec.intervention_date,
        pre_period_start=spec.pre_period_start,
        pre_period_end=spec.pre_period_end,
        post_period_start=spec.post_period_start,
        post_period_end=spec.post_period_end,
        kpi_type=spec.kpi_type,
        backend=backend,
        cumulative_effect=result_dict["cumulative_effect"],
        cumulative_effect_lower=result_dict["cumulative_effect_lower"],
        cumulative_effect_upper=result_dict["cumulative_effect_upper"],
        relative_effect_pct=result_dict["relative_effect_pct"],
        p_value=result_dict["p_value"],
        prob_causal=prob_causal,
    )

    # Step 5: build the time-series points from the inferences.
    time_series_points = _build_time_series_points(
        analysis_id=analysis_id,
        inferences=result_dict["inferences"],
        ts=ts,
        backend=backend,
    )

    return AnalysisResult(summary=summary, time_series=time_series_points)


def _build_time_series_points(
    analysis_id: str,
    inferences: pd.DataFrame,
    ts: pd.DataFrame,
    backend: str,
) -> List[TimeSeriesPoint]:
    """
    Convert the inferences DataFrame into a list of TimeSeriesPoint objects.
    Handles the different column naming conventions across backends.
    """
    points: List[TimeSeriesPoint] = []

    # Normalize column names depending on backend.
    if backend in ("tfcausalimpact", "pycausalimpact"):
        # Column names vary by package version; try common patterns.
        actual_col = _find_col(inferences, ["response", "y", "actual"])
        pred_col = _find_col(inferences, ["point_pred", "preds", "predicted", "complete_preds_means"])
        pred_lower_col = _find_col(inferences, ["point_pred_lower", "preds_lower", "predicted_lower",
                                                "complete_preds_lower"])
        pred_upper_col = _find_col(inferences, ["point_pred_upper", "preds_upper", "predicted_upper",
                                                "complete_preds_upper"])
        effect_col = _find_col(inferences, ["point_effect", "point_effects_means"])
        cum_col = _find_col(inferences, ["post_cum_y", "post_cum_effects_means", "cumulative_effect"])
    else:
        # The from-scratch fallback uses our own column names.
        actual_col = "actual"
        pred_col = "predicted"
        pred_lower_col = "predicted_lower"
        pred_upper_col = "predicted_upper"
        effect_col = "point_effect"
        cum_col = "cumulative_effect"

    for idx in inferences.index:
        dt = idx.date() if hasattr(idx, "date") else idx

        actual_val = _safe_float(inferences, idx, actual_col)
        # If actual is not in inferences, get it from the original series.
        if actual_val == 0.0 and actual_col is None:
            ts_idx = pd.to_datetime(dt)
            if hasattr(ts.index, "get_loc"):
                try:
                    ts_dt = dt
                    if ts_dt in ts.index:
                        actual_val = float(ts.loc[ts_dt, "y"])
                    elif ts_idx in ts.index:
                        actual_val = float(ts.loc[ts_idx, "y"])
                except (KeyError, TypeError):
                    pass

        predicted_val = _safe_float(inferences, idx, pred_col)
        predicted_lower_val = _safe_float(inferences, idx, pred_lower_col)
        predicted_upper_val = _safe_float(inferences, idx, pred_upper_col)
        point_effect_val = _safe_float(inferences, idx, effect_col)
        cum_effect_val = _safe_float(inferences, idx, cum_col)

        points.append(TimeSeriesPoint(
            analysis_id=analysis_id,
            date=dt,
            actual=actual_val,
            predicted=predicted_val,
            predicted_lower=predicted_lower_val,
            predicted_upper=predicted_upper_val,
            point_effect=point_effect_val,
            cumulative_effect=cum_effect_val,
        ))

    return points


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find the first matching column name from a list of candidates."""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _safe_float(df: pd.DataFrame, idx, col: Optional[str]) -> float:
    """Safely extract a float value from a DataFrame cell."""
    if col is None or col not in df.columns:
        return 0.0
    try:
        val = df.loc[idx, col]
        if pd.isna(val):
            return 0.0
        return float(val)
    except (KeyError, TypeError, ValueError):
        return 0.0
