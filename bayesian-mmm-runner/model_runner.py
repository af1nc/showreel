"""
Model fitting and analysis for a Bayesian Marketing Mix Model (MMM).

Configures a Meridian ModelSpec, fits the model via MCMC sampling,
extracts ROI/mROI/response curves using Analyzer, and runs
BudgetOptimizer for spend allocation scenarios.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import xarray as xr

from config import (
    BUDGET_OPT_LOWER_BOUND,
    BUDGET_OPT_UPPER_BOUND,
    KPI_CONFIGS,
    MODEL_CHANNELS,
    MODEL_PARAMS,
    RESPONSE_CURVE_MULTIPLIERS,
    ModelHyperparameters,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Result Containers
# =============================================================================

@dataclass
class ChannelMetrics:
    """Per-channel ROI, mROI, and contribution metrics."""
    channel: str
    roi_mean: float
    roi_lower: float
    roi_upper: float
    mroi_mean: float
    mroi_lower: float
    mroi_upper: float
    contribution_pct: float
    total_spend: float
    incremental_outcome: float
    prob_profitable: float


@dataclass
class ResponseCurvePoint:
    """A single point on a channel's response curve."""
    channel: str
    spend_multiplier: float
    spend_amount: float
    response_mean: float
    response_lower: float
    response_upper: float


@dataclass
class BudgetOptResult:
    """Budget optimization result for a single channel+scenario."""
    scenario: str
    channel: str
    current_spend: float
    optimized_spend: float
    current_outcome: float
    optimized_outcome: float
    pct_change: float


@dataclass
class WeeklyContribution:
    """Weekly channel-level contribution to KPI."""
    week_start: str  # ISO date string
    channel: str
    contribution: float
    actual_kpi: float
    predicted_kpi: float


@dataclass
class ModelResults:
    """Complete model output for a single run."""
    r_squared: float
    mape: float
    channel_metrics: List[ChannelMetrics]
    response_curves: List[ResponseCurvePoint]
    budget_optimization: List[BudgetOptResult]
    weekly_contributions: List[WeeklyContribution]


# =============================================================================
# Model Configuration
# =============================================================================

def configure_model_spec(
    n_channels: int,
    params: ModelHyperparameters,
):
    """
    Create a Meridian ModelSpec with ROI priors and adstock config.
    """
    from meridian.model import spec as model_spec

    logger.info("Configuring ModelSpec with %d channels, max_lag=%d", n_channels, params.max_lag)

    # ROI prior: LogNormal for all channels
    # shape: (n_channels,) for mu and sigma
    roi_prior_mu = np.full(n_channels, params.roi_prior_mu)
    roi_prior_sigma = np.full(n_channels, params.roi_prior_sigma)

    media_channel_spec = model_spec.ModelSpec(
        max_lag=params.max_lag,
        roi_calibration_period=None,  # Use full period
    )

    return media_channel_spec


def fit_model(
    input_data,
    params: ModelHyperparameters,
):
    """
    Create and fit a Meridian model.

    Args:
        input_data: Meridian InputData object from data_prep
        params: Model hyperparameters

    Returns:
        model: Fitted Meridian model
    """
    from meridian.model import model as meridian_model
    from meridian.model import spec as model_spec

    logger.info("=" * 60)
    logger.info("MODEL FITTING")
    logger.info("=" * 60)

    n_channels = len(MODEL_CHANNELS)

    # Create model spec
    spec = model_spec.ModelSpec(
        max_lag=params.max_lag,
    )

    # Create the Meridian model
    logger.info("Creating Meridian model...")
    model = meridian_model.Meridian(
        input_data=input_data,
        model_spec=spec,
    )

    # Fit the model (MCMC sampling)
    logger.info(
        "Starting MCMC sampling: %d chains, %d adapt, %d burnin, %d keep",
        params.n_chains,
        params.n_adapt,
        params.n_burnin,
        params.n_keep,
    )

    model.sample_posterior(
        n_chains=params.n_chains,
        n_adapt=params.n_adapt,
        n_burnin=params.n_burnin,
        n_keep=params.n_keep,
    )

    logger.info("MCMC sampling complete.")

    # Save model to /tmp for debugging (can be loaded later if needed)
    try:
        from meridian.schema.serde import meridian_serde
        model_path = "/tmp/meridian_model.pkl"
        meridian_serde.save(model, model_path)
        logger.info("Model saved to %s", model_path)
    except Exception as e:
        logger.warning("Failed to save model to disk: %s", e)

    return model


# =============================================================================
# Result Extraction
# =============================================================================

def extract_results(
    model,
    weekly_df,
    weeks: list,
    kpi_type: str,
    params: ModelHyperparameters,
) -> ModelResults:
    """
    Extract all results from a fitted Meridian model using Analyzer.

    Returns a ModelResults object containing channel metrics,
    response curves, budget optimization, and weekly contributions.
    """
    from meridian.analysis import analyzer as meridian_analyzer
    from meridian.analysis import optimizer as meridian_optimizer

    logger.info("=" * 60)
    logger.info("EXTRACTING RESULTS")
    logger.info("=" * 60)

    kpi_config = KPI_CONFIGS[kpi_type]
    kpi_col = kpi_config.column

    # Create analyzer - Meridian v1.x requires model_context + inference_data
    az = meridian_analyzer.Analyzer(
        model_context=model.model_context,
        inference_data=model.inference_data,
    )

    # ---- Predictive accuracy ----
    r_squared = _extract_r_squared(az)
    mape = _extract_mape(az)
    logger.info("Model fit: R-squared=%.4f, MAPE=%.4f", r_squared, mape)

    # ---- Channel metrics (ROI, mROI, contribution) ----
    channel_metrics = _extract_channel_metrics(az, weekly_df, kpi_type)

    # ---- Response curves ----
    response_curves = _extract_response_curves(az, weekly_df)

    # ---- Budget optimization ----
    budget_optimization = _extract_budget_optimization(
        model, az, weekly_df, kpi_type
    )

    # ---- Weekly contributions ----
    weekly_contributions = _extract_weekly_contributions(
        az, weekly_df, weeks, kpi_type
    )

    return ModelResults(
        r_squared=r_squared,
        mape=mape,
        channel_metrics=channel_metrics,
        response_curves=response_curves,
        budget_optimization=budget_optimization,
        weekly_contributions=weekly_contributions,
    )


# Candidate variable names / metric coords for the predictive_accuracy() Dataset.
# Meridian has shifted naming across versions; do case-insensitive matching.
_R_SQUARED_CANDIDATES = ("R_Squared", "r_squared", "R2", "RSquared")
# MAPE returns Infinity when any actual KPI value is 0 (division by zero in the
# unweighted formula). wMAPE / SMAPE handle zero actuals gracefully - try those
# first so callers get a real number whenever Meridian provides one.
_MAPE_CANDIDATES = ("wMAPE", "wmape", "SMAPE", "smape", "MAPE", "mape", "Mape")
# Preferred order of metric-dim coords when present.
_METRIC_PREFERENCE = ("All_Data", "Test", "Train")


def _resolve_var_name(ds: xr.Dataset, candidates) -> Optional[str]:
    """Return the variable name from `candidates` that exists in `ds` (case-insensitive)."""
    if not isinstance(ds, xr.Dataset):
        return None
    lower_to_actual = {str(name).lower(): str(name) for name in ds.data_vars}
    for cand in candidates:
        actual = lower_to_actual.get(cand.lower())
        if actual is not None:
            return actual
    return None


def _scalar_from_metric_dim(da: xr.DataArray) -> float:
    """Reduce a DataArray to a scalar, preferring known metric-dim coords."""
    metric_dim = None
    for dim in da.dims:
        if str(dim).lower() in ("metric", "evaluation_set", "split"):
            metric_dim = dim
            break

    if metric_dim is not None:
        coord_values = [str(v) for v in da.coords[metric_dim].values]
        coord_lookup = {v.lower(): v for v in coord_values}
        for preferred in _METRIC_PREFERENCE:
            actual = coord_lookup.get(preferred.lower())
            if actual is not None:
                try:
                    return float(da.sel({metric_dim: actual}).values.flat[0])
                except Exception:
                    continue
        # Fallback: mean over the metric dim
        try:
            return float(da.mean(dim=metric_dim).values.flat[0])
        except Exception:
            pass

    # No metric dim - pull the first scalar value
    return float(da.values.flat[0])


def _extract_predictive_metric(az, candidates, label: str) -> float:
    """Extract R² / MAPE from Meridian's predictive_accuracy() output.

    Meridian's modern API returns a Dataset with a single var (typically 'value')
    and a `metric` coord dim whose values are 'R_Squared'/'MAPE'/'wMAPE'.
    We look up the metric by coord value, not by variable name.

    Older Meridian versions exposed each metric as its own variable - we still
    handle that as a fallback.

    Returns NaN on failure (NOT 0.0) so failed runs don't pollute downstream metrics.
    """
    try:
        pa = az.predictive_accuracy()
    except Exception as e:
        logger.warning("predictive_accuracy() call failed for %s: %s", label, e)
        return float("nan")

    if not isinstance(pa, xr.Dataset):
        if hasattr(pa, "to_dataframe"):
            try:
                df = pa.to_dataframe().reset_index()
                lower_to_actual = {str(c).lower(): str(c) for c in df.columns}
                for cand in candidates:
                    actual = lower_to_actual.get(cand.lower())
                    if actual is not None:
                        return float(df[actual].iloc[0])
            except Exception as e:
                logger.warning("predictive_accuracy DataFrame fallback failed for %s: %s", label, e)
        logger.warning(
            "predictive_accuracy() returned unexpected type %s for %s",
            type(pa).__name__, label,
        )
        return float("nan")

    # PRIMARY PATH: single 'value' var keyed by metric coord (modern Meridian).
    # Iterate every var; for each, look at its 'metric' (or similar) dim coord values
    # and try to .sel() by any matching candidate.
    # Skip values that are inf (e.g. unweighted MAPE divides by zero when actuals=0)
    # so we fall through to the next candidate (typically wMAPE / SMAPE).
    metric_dim_aliases = ("metric", "metric_name", "predictive_metric")
    inf_fallback = None  # remember the inf so we return it if NOTHING else worked
    for var_name in pa.data_vars:
        da = pa[var_name]
        metric_dim = next(
            (d for d in da.dims if str(d).lower() in metric_dim_aliases),
            None,
        )
        if metric_dim is None:
            continue
        try:
            coord_values = [str(v) for v in da.coords[metric_dim].values]
        except Exception:
            continue
        coord_lookup = {v.lower(): v for v in coord_values}
        for cand in candidates:
            actual = coord_lookup.get(cand.lower())
            if actual is None:
                continue
            try:
                arr = da.sel({metric_dim: actual})
                while arr.dims:
                    arr = arr.mean(dim=arr.dims[0])
                value = float(arr.values)
                if not np.isfinite(value):
                    inf_fallback = value if inf_fallback is None else inf_fallback
                    continue
                return value
            except Exception as e:
                logger.warning(
                    "Failed to .sel(%s='%s') on var '%s' for %s: %s",
                    metric_dim, actual, var_name, label, e,
                )
    if inf_fallback is not None:
        # Every candidate was inf - return it; signals zero-actual divide-by-zero
        # rather than masking with NaN.
        return inf_fallback

    # FALLBACK PATH: legacy Meridian where each metric was its own data_var.
    var_name = _resolve_var_name(pa, candidates)
    if var_name is not None:
        try:
            return _scalar_from_metric_dim(pa[var_name])
        except Exception as e:
            logger.warning(
                "Legacy fallback failed for %s='%s': %s. dims=%s",
                label, var_name, e, pa[var_name].dims,
            )

    # Final diagnostic dump.
    sample_coords = {}
    for d in pa.dims:
        try:
            sample_coords[d] = [str(v) for v in pa.coords[d].values[:5]]
        except Exception:
            sample_coords[d] = "<no coords>"
    logger.warning(
        "Could not find %s in predictive_accuracy. data_vars=%s, dims=%s, sample_coords=%s",
        label, list(pa.data_vars), dict(pa.dims), sample_coords,
    )
    return float("nan")


def _extract_r_squared(az) -> float:
    """Extract R-squared (case-insensitive, metric-dim aware). Returns NaN on failure."""
    return _extract_predictive_metric(az, _R_SQUARED_CANDIDATES, "R-squared")


def _extract_mape(az) -> float:
    """Extract MAPE (case-insensitive, metric-dim aware). Returns NaN on failure."""
    return _extract_predictive_metric(az, _MAPE_CANDIDATES, "MAPE")


def _resolve_var_by_substrings(ds, substrings):
    """Find a data_var in `ds` whose name matches any candidate (case-insensitive
    substring match). Returns the actual var name or None.

    Order matters: we try exact-match-first within each substring, then partial.
    """
    if not isinstance(ds, xr.Dataset):
        return None
    var_names = [str(v) for v in ds.data_vars]
    lowered = {v.lower(): v for v in var_names}
    # Exact (case-insensitive) match first
    for sub in substrings:
        actual = lowered.get(sub.lower())
        if actual is not None:
            return actual
    # Substring fallback
    for sub in substrings:
        sub_l = sub.lower()
        for v in var_names:
            if sub_l in v.lower():
                return v
    return None


def _dump_ds_diag(label, ds):
    """Emit a diagnostic dump of a Dataset's vars/dims/coords (truncated)."""
    if not isinstance(ds, xr.Dataset):
        logger.warning("%s: not a Dataset (type=%s)", label, type(ds).__name__)
        return
    sample_coords = {}
    for d in ds.dims:
        try:
            sample_coords[d] = [str(v) for v in ds.coords[d].values[:8]]
        except Exception:
            sample_coords[d] = "<no coords>"
    logger.warning(
        "%s diagnostics - data_vars=%s, dims=%s, sample_coords=%s",
        label, list(ds.data_vars), dict(ds.dims), sample_coords,
    )


def _extract_channel_metrics(
    az,
    weekly_df,
    kpi_type: str,
) -> List[ChannelMetrics]:
    """Extract per-channel ROI, mROI, contribution, and spend.

    Uses two approaches:
    1. summary_metrics() xr.Dataset for point estimates and CIs
    2. roi()/marginal_roi() raw posterior tensors for prob_profitable

    Defensive var-name resolution: Meridian has shifted naming across versions
    (e.g. 'roi' vs 'ROI', 'pct_contribution' vs 'pct_of_contribution' vs
    'Contribution'). We resolve via case-insensitive substring matching against
    actual data_vars present, and dump the Dataset shape if nothing matches.
    """
    logger.info("Extracting channel metrics...")

    kpi_config = KPI_CONFIGS[kpi_type]
    metrics = []

    # --- Approach 1: summary_metrics() for point estimates ---
    summary = None
    try:
        summary = az.summary_metrics()
        logger.info("summary_metrics() type: %s", type(summary).__name__)
        if isinstance(summary, xr.Dataset):
            logger.info("summary_metrics data_vars: %s", list(summary.data_vars))
            logger.info("summary_metrics dims: %s", dict(summary.dims))
            logger.info("summary_metrics coord names: %s", list(summary.coords))
    except Exception as e:
        logger.warning("summary_metrics() failed: %s", e)

    # Pre-resolve actual var names once, log misses up-front so a bad version
    # doesn't silently emit zero-filled rows for every channel.
    resolved_vars = {}
    if isinstance(summary, xr.Dataset):
        resolved_vars["roi"] = _resolve_var_by_substrings(summary, ["roi", "ROI"])
        resolved_vars["mroi"] = _resolve_var_by_substrings(
            summary, ["mroi", "marginal_roi", "MROI"]
        )
        resolved_vars["contribution"] = _resolve_var_by_substrings(
            summary,
            [
                "pct_contribution",
                "pct_of_contribution",
                "contribution_pct",
                "Contribution",
                "contribution",
            ],
        )
        resolved_vars["incremental_outcome"] = _resolve_var_by_substrings(
            summary,
            ["incremental_outcome", "incremental", "outcome"],
        )
        logger.info("Resolved summary_metrics var names: %s", resolved_vars)
        # If any critical var is missing, dump the dataset shape so we can fix.
        if not resolved_vars.get("roi") or not resolved_vars.get("contribution"):
            _dump_ds_diag("summary_metrics MISSING expected vars", summary)

    # --- Approach 2: raw posterior distributions for ROI/mROI/contribution ---
    roi_tensor = None
    mroi_tensor = None
    incremental_per_channel = None  # Used as fallback for contribution_pct
    try:
        roi_tensor = az.roi()
        logger.info("roi() shape: %s, type: %s", getattr(roi_tensor, "shape", "?"), type(roi_tensor).__name__)
    except Exception as e:
        logger.warning("roi() failed: %s", e)

    try:
        mroi_tensor = az.marginal_roi()
        logger.info("marginal_roi() shape: %s, type: %s", getattr(mroi_tensor, "shape", "?"), type(mroi_tensor).__name__)
    except Exception as e:
        logger.warning("marginal_roi() failed: %s", e)

    # Used to compute contribution_pct as a fallback when summary_metrics
    # doesn't expose pct_of_contribution / pct_contribution / Contribution.
    try:
        incremental_per_channel = az.incremental_outcome(
            aggregate_geos=True,
            aggregate_times=True,
        )
        if isinstance(incremental_per_channel, xr.Dataset):
            inc_v = _resolve_var_by_substrings(
                incremental_per_channel,
                ["incremental_outcome", "incremental", "outcome"],
            )
            if inc_v is None:
                _dump_ds_diag(
                    "incremental_outcome aggregate=True (Dataset, no var)",
                    incremental_per_channel,
                )
                incremental_per_channel = None
            else:
                incremental_per_channel = incremental_per_channel[inc_v].values
        logger.info(
            "incremental_outcome(aggregate=True) shape: %s",
            getattr(incremental_per_channel, "shape", "?"),
        )
    except Exception as e:
        logger.warning("incremental_outcome() for contribution fallback failed: %s", e)

    # --- Helper to get a scalar from summary_metrics xr.Dataset ---
    def _get_summary_val(ds, var_name, channel_name, metric_name="mean"):
        """Extract a float from summary_metrics Dataset."""
        try:
            if not isinstance(ds, xr.Dataset) or var_name not in ds.data_vars:
                return None
            val = ds[var_name]
            sel_kwargs = {}
            if "distribution" in val.dims:
                sel_kwargs["distribution"] = "posterior"
            if "metric" in val.dims:
                sel_kwargs["metric"] = metric_name
            if "channel" in val.dims:
                sel_kwargs["channel"] = channel_name
            result = val.sel(**sel_kwargs)
            return float(result.values.flat[0])
        except (KeyError, IndexError, ValueError) as exc:
            logger.debug("_get_summary_val(%s, %s, %s) failed: %s", var_name, channel_name, metric_name, exc)
            return None

    # --- Helper to extract channel posterior samples from raw tensor ---
    def _get_posterior_channel(tensor, ch_idx):
        """Extract flattened posterior samples for a channel from a tensor.
        Tensor shape is typically (n_chains, n_draws, n_channels) when
        geos and times are aggregated.
        """
        if tensor is None:
            return None
        arr = np.asarray(tensor)
        # Last dim is channels
        if arr.ndim >= 2 and ch_idx < arr.shape[-1]:
            return arr[..., ch_idx].flatten()
        if arr.ndim == 1 and ch_idx < len(arr):
            return np.array([arr[ch_idx]])
        return None

    # Get channel names as they appear in the summary_metrics Dataset
    summary_channel_names = None
    if isinstance(summary, xr.Dataset) and "channel" in summary.coords:
        summary_channel_names = list(summary.coords["channel"].values)
        logger.info("summary_metrics channel names: %s", summary_channel_names)

    # Authoritative model channel order. data_prep.build_input_data passes
    # media_channels = [ch for ch in MODEL_CHANNELS if spend > 0], so EVERY
    # Meridian output (summary_metrics, roi(), incremental_outcome(),
    # response_curves(), optimizer) carries its channel dim in this exact order.
    # We map MODEL_CHANNELS -> model position BY NAME; channels not present were
    # dropped (zero spend) and must receive genuine zero rows - never a
    # positionally-shifted neighbour's value. 
    active_order = [
        ch for ch in MODEL_CHANNELS
        if float(weekly_df.loc[weekly_df["channel"] == ch, "spend"].sum()) > 0
    ]
    active_pos = {ch: i for i, ch in enumerate(active_order)}

    # Per-channel incremental-outcome posterior means (active-channel order),
    # computed ONCE. Used for both the incremental_outcome field and a
    # CONSISTENT contribution share (channel incremental / total incremental,
    # summing to ~100%). Deriving contribution from the name-aligned incremental
    # posterior avoids summary_metrics' ambiguous fraction-vs-percent scaling,
    # whose "<1.0 -> *100" guard previously inflated sub-1% channels (email, ooh)
    # ~100x and broke the 100% contribution sum.
    incremental_means = None
    incremental_total = 0.0
    if incremental_per_channel is not None:
        try:
            _inc = np.asarray(incremental_per_channel)
            if _inc.ndim >= 2:
                incremental_means = np.mean(_inc.reshape(-1, _inc.shape[-1]), axis=0)
            elif _inc.ndim == 1:
                incremental_means = _inc
            if incremental_means is not None:
                incremental_total = float(np.sum(incremental_means))
        except Exception as exc:
            logger.warning("Incremental means precompute failed: %s", exc)

    for channel in MODEL_CHANNELS:
        ch_spend = weekly_df.loc[
            weekly_df["channel"] == channel, "spend"
        ].sum()

        # Channels with zero spend were dropped from the fitted model, so they
        # have no posterior. Emit a GENUINE zero row rather than borrowing a
        # neighbour's value through positional indexing. 
        if float(ch_spend) <= 0 or channel not in active_pos:
            metrics.append(ChannelMetrics(
                channel=channel,
                roi_mean=0.0, roi_lower=0.0, roi_upper=0.0,
                mroi_mean=0.0, mroi_lower=0.0, mroi_upper=0.0,
                contribution_pct=0.0,
                total_spend=float(ch_spend),
                incremental_outcome=0.0,
                prob_profitable=0.0,
            ))
            continue

        # Select strictly BY NAME from summary_metrics, and by model position
        # (active_pos) from the raw posterior tensors - both resolve to THIS
        # channel, never a positional neighbour.
        sm_channel = channel
        tensor_idx = active_pos[channel]

        # --- ROI from summary_metrics (use resolved var name) ---
        roi_var = resolved_vars.get("roi") or "roi"
        roi_mean = _get_summary_val(summary, roi_var, sm_channel, "mean") or 0.0
        roi_lower = _get_summary_val(summary, roi_var, sm_channel, "ci_lo") or 0.0
        roi_upper = _get_summary_val(summary, roi_var, sm_channel, "ci_hi") or 0.0

        # --- mROI from summary_metrics ---
        mroi_var = resolved_vars.get("mroi") or "mroi"
        mroi_mean = _get_summary_val(summary, mroi_var, sm_channel, "mean") or 0.0
        mroi_lower = _get_summary_val(summary, mroi_var, sm_channel, "ci_lo") or 0.0
        mroi_upper = _get_summary_val(summary, mroi_var, sm_channel, "ci_hi") or 0.0

        # --- Per-channel incremental outcome (name-aligned via tensor_idx) ---
        channel_incremental = None
        if incremental_means is not None and tensor_idx < len(incremental_means):
            channel_incremental = float(incremental_means[tensor_idx])

        # --- Contribution share = channel incremental / total media incremental.
        # Internally consistent (sums to ~100% across channels) and consistent
        # with roi_mean * total_spend.  ---
        if channel_incremental is not None and incremental_total > 0:
            contribution_pct = channel_incremental / incremental_total * 100.0
        else:
            # No incremental posterior available - fall back to summary_metrics'
            # contribution var. Only THIS path may legitimately be a 0-1 fraction.
            contrib_var = resolved_vars.get("contribution")
            contribution_pct = (
                _get_summary_val(summary, contrib_var, sm_channel, "mean")
                if contrib_var else None
            )
            if contribution_pct is None:
                logger.warning(
                    "Could not extract contribution_pct for %s - defaulting to 0.0",
                    channel,
                )
                contribution_pct = 0.0
            elif 0 < contribution_pct < 1.0:
                contribution_pct *= 100.0  # summary fraction -> percent

        # --- Incremental outcome: prefer summary_metrics, fall back to the
        # name-aligned posterior mean (summary_metrics often omits it, which is
        # why this was 0 for every channel before).  ---
        inc_var = resolved_vars.get("incremental_outcome") or "incremental_outcome"
        incremental_outcome = _get_summary_val(summary, inc_var, sm_channel, "mean")
        if incremental_outcome is None:
            incremental_outcome = (
                channel_incremental if channel_incremental is not None else 0.0
            )

        # --- Probability of being profitable (from raw posterior) ---
        threshold = 1.0 if kpi_config.is_revenue else 0.0
        roi_posterior = _get_posterior_channel(roi_tensor, tensor_idx)
        if roi_posterior is not None and len(roi_posterior) > 1:
            prob_profitable = float(np.mean(roi_posterior > threshold))
            # If summary_metrics ROI was 0 but posterior is available, use posterior
            if roi_mean == 0.0:
                roi_mean = float(np.mean(roi_posterior))
                roi_lower = float(np.percentile(roi_posterior, 5))
                roi_upper = float(np.percentile(roi_posterior, 95))
        else:
            prob_profitable = 1.0 if roi_mean > threshold else 0.0

        # If summary_metrics mROI was 0 but posterior is available, use posterior
        mroi_posterior = _get_posterior_channel(mroi_tensor, tensor_idx)
        if mroi_mean == 0.0 and mroi_posterior is not None and len(mroi_posterior) > 1:
            mroi_mean = float(np.mean(mroi_posterior))
            mroi_lower = float(np.percentile(mroi_posterior, 5))
            mroi_upper = float(np.percentile(mroi_posterior, 95))

        metrics.append(ChannelMetrics(
            channel=channel,
            roi_mean=roi_mean,
            roi_lower=roi_lower,
            roi_upper=roi_upper,
            mroi_mean=mroi_mean,
            mroi_lower=mroi_lower,
            mroi_upper=mroi_upper,
            contribution_pct=contribution_pct,
            total_spend=float(ch_spend),
            incremental_outcome=incremental_outcome,
            prob_profitable=prob_profitable,
        ))

        logger.info(
            "  %s: ROI=%.2f [%.2f, %.2f], mROI=%.2f, contrib=%.1f%%, spend=$%.0fK",
            channel,
            roi_mean, roi_lower, roi_upper,
            mroi_mean,
            contribution_pct,
            ch_spend / 1000,
        )

    return metrics


def _safe_channel_samples(arr, ch_idx: int) -> np.ndarray:
    """
    Safely extract channel samples from various Meridian output shapes.
    Handles both (n_samples, n_channels) and dict-of-arrays formats.
    """
    if isinstance(arr, dict):
        # Some Meridian methods return dicts keyed by channel name
        channel = MODEL_CHANNELS[ch_idx]
        if channel in arr:
            val = arr[channel]
            return np.atleast_1d(val).flatten()
    if isinstance(arr, np.ndarray):
        if arr.ndim == 2 and ch_idx < arr.shape[1]:
            return arr[:, ch_idx].flatten()
        if arr.ndim == 3 and ch_idx < arr.shape[2]:
            # (n_chains, n_samples, n_channels) - flatten chains
            return arr[:, :, ch_idx].flatten()
        if arr.ndim == 1:
            return arr
    # Fallback: try to index directly
    try:
        val = arr[ch_idx]
        return np.atleast_1d(val).flatten()
    except (IndexError, KeyError, TypeError):
        logger.warning("Could not extract channel %d from array shape %s", ch_idx, getattr(arr, "shape", "unknown"))
        return np.array([0.0])


def _extract_response_curves(
    az,
    weekly_df,
) -> List[ResponseCurvePoint]:
    """
    Evaluate response curves at various spend multipliers.

    Meridian v1.x: az.response_curves(spend_multipliers=[...]) returns an
    xr.Dataset with coords (channel/media, metric, spend_multiplier) and
    data vars: 'spend', 'incremental_outcome', 'roi'.
    """
    logger.info("Extracting response curves at %d spend levels...", len(RESPONSE_CURVE_MULTIPLIERS))

    results = []

    # Compute current spend per channel for fallback spend_amount calculation
    ch_spend_map = {}
    for channel in MODEL_CHANNELS:
        ch_spend_map[channel] = float(
            weekly_df.loc[weekly_df["channel"] == channel, "spend"].sum()
        )

    try:
        # Call response_curves once with all multipliers
        rc_ds = az.response_curves(spend_multipliers=RESPONSE_CURVE_MULTIPLIERS)
        logger.info("response_curves() type: %s", type(rc_ds).__name__)

        if isinstance(rc_ds, xr.Dataset):
            logger.info("response_curves data_vars: %s", list(rc_ds.data_vars))
            logger.info("response_curves coords: %s", {k: list(v.values) for k, v in rc_ds.coords.items() if len(v) < 50})

            # Determine the channel dimension name (could be 'channel' or 'media')
            ch_dim = None
            for dim_name in ("channel", "media"):
                if dim_name in rc_ds.coords:
                    ch_dim = dim_name
                    break

            if ch_dim is None:
                logger.warning("response_curves Dataset has no 'channel' or 'media' coord, dims: %s", list(rc_ds.dims))
                raise ValueError("No channel coordinate in response_curves output")

            rc_channel_names = list(rc_ds.coords[ch_dim].values)
            logger.info("response_curves channel names: %s", rc_channel_names)

            # Determine the outcome variable name (case-insensitive substring)
            outcome_var = _resolve_var_by_substrings(
                rc_ds,
                ["incremental_outcome", "response", "outcome", "response_mean"],
            )
            if outcome_var is None:
                _dump_ds_diag("response_curves outcome var NOT FOUND", rc_ds)
                if rc_ds.data_vars:
                    outcome_var = list(rc_ds.data_vars)[0]
                    logger.warning(
                        "Falling back to first data var as outcome: %s", outcome_var,
                    )
                else:
                    raise ValueError("response_curves Dataset has no data_vars")

            # Determine the spend variable name (case-insensitive)
            spend_var = _resolve_var_by_substrings(rc_ds, ["spend", "spend_amount"])
            if spend_var is None:
                logger.warning(
                    "response_curves has no 'spend' var - falling back to multiplier*current_spend",
                )

            rc_channel_set = set(map(str, rc_channel_names))
            # method="nearest" requires a monotonic index - make sure the
            # spend_multiplier coord is sorted before any nearest select.
            if "spend_multiplier" in rc_ds.coords:
                rc_ds = rc_ds.sortby("spend_multiplier")

            for channel in MODEL_CHANNELS:
                # Match the curve channel strictly BY NAME. Channels dropped from
                # the fitted model aren't in the curve output - skip rather than
                # positionally mislabel another channel's curve. 
                if str(channel) not in rc_channel_set:
                    continue
                rc_ch_name = channel

                for multiplier in RESPONSE_CURVE_MULTIPLIERS:
                    try:
                        # Exact-match the (string) channel dim, then nearest-match
                        # ONLY the numeric spend_multiplier. Applying
                        # method="nearest" to the string channel dim is what
                        # raised "index must be monotonic increasing or
                        # decreasing" and left response_curves empty. 
                        outcome_da = rc_ds[outcome_var].sel({ch_dim: rc_ch_name}).sel(
                            spend_multiplier=multiplier, method="nearest",
                        )
                        if "metric" in outcome_da.dims:
                            resp_mean = float(outcome_da.sel(metric="mean").values.flat[0])
                            resp_lower = float(outcome_da.sel(metric="ci_lo").values.flat[0])
                            resp_upper = float(outcome_da.sel(metric="ci_hi").values.flat[0])
                        else:
                            resp_mean = float(outcome_da.values.flat[0])
                            resp_lower = resp_mean
                            resp_upper = resp_mean

                        # Get spend amount from dataset or compute from multiplier
                        if spend_var:
                            spend_da = rc_ds[spend_var].sel({ch_dim: rc_ch_name}).sel(
                                spend_multiplier=multiplier, method="nearest",
                            )
                            if "metric" in spend_da.dims:
                                spend_amount = float(spend_da.sel(metric="mean").values.flat[0])
                            else:
                                spend_amount = float(spend_da.values.flat[0])
                        else:
                            spend_amount = ch_spend_map[channel] * multiplier
                    except Exception as e:
                        # Skip this point entirely rather than emitting a fake
                        # zero row. Missing data is preferable to misleading data.
                        logger.warning(
                            "Response curve extraction failed for %s at %.2fx - skipping point: %s",
                            channel, multiplier, e,
                        )
                        continue

                    results.append(ResponseCurvePoint(
                        channel=channel,
                        spend_multiplier=multiplier,
                        spend_amount=spend_amount,
                        response_mean=resp_mean,
                        response_lower=resp_lower,
                        response_upper=resp_upper,
                    ))
        else:
            raise ValueError(f"Unexpected response_curves return type: {type(rc_ds)}")

    except Exception as e:
        # Don't emit fake zero rows - that pollutes downstream analysis.
        # Better to leave the table empty for this run; the missing data
        # itself is the signal something went wrong.
        logger.error(
            "response_curves() failed entirely - emitting no rows for this run: %s",
            e,
        )

    logger.info("Extracted %d response curve points.", len(results))
    return results


def _extract_budget_optimization(
    model,
    az,
    weekly_df,
    kpi_type: str,
) -> List[BudgetOptResult]:
    """
    Run budget optimization: fixed total budget, redistribute across channels.

    Meridian v1.x: BudgetOptimizer(meridian=model), then optimize() returns
    OptimizationResults with .optimized_data and .nonoptimized_data as
    xr.Datasets. Each has data vars: spend, roi, mroi, incremental_outcome,
    pct_of_spend, cpik, effectiveness - with coords (channel, metric).
    """
    from meridian.analysis import optimizer as meridian_optimizer

    logger.info("Running budget optimization...")

    results = []

    # Current spend per channel
    current_spend = {}
    for channel in MODEL_CHANNELS:
        current_spend[channel] = float(
            weekly_df.loc[weekly_df["channel"] == channel, "spend"].sum()
        )

    total_budget = sum(current_spend.values())
    logger.info("Total budget for optimization: $%.2fM", total_budget / 1e6)

    try:
        # Create optimizer - Meridian v1.x takes just the model
        opt = meridian_optimizer.BudgetOptimizer(meridian=model)

        # Use scalar constraints. Lists must match the number of channels the model was
        # actually fit on, which is <= len(MODEL_CHANNELS) since some channels (metasearch,
        # email, ooh, tv) won't have data in every market/window. Scalars apply to all.
        opt_result = opt.optimize(
            budget=total_budget,
            fixed_budget=True,
            spend_constraint_lower=BUDGET_OPT_LOWER_BOUND,
            spend_constraint_upper=BUDGET_OPT_UPPER_BOUND,
        )

        logger.info("BudgetOptimizer.optimize() returned: %s", type(opt_result).__name__)

        # Extract from optimized_data xr.Dataset
        opt_data = opt_result.optimized_data
        nonopt_data = opt_result.nonoptimized_data

        logger.info("optimized_data type: %s", type(opt_data).__name__)
        if isinstance(opt_data, xr.Dataset):
            logger.info("optimized_data vars: %s", list(opt_data.data_vars))
            logger.info("optimized_data dims: %s", dict(opt_data.dims))
            logger.info("optimized_data coord names: %s", list(opt_data.coords))
        if isinstance(nonopt_data, xr.Dataset):
            logger.info("nonoptimized_data vars: %s", list(nonopt_data.data_vars))

        # Determine channel dim name
        ch_dim = None
        if isinstance(opt_data, xr.Dataset):
            for dim_name in ("channel", "media", "media_channel"):
                if dim_name in opt_data.coords:
                    ch_dim = dim_name
                    break

        # Resolve actual var names case-insensitively across both datasets.
        spend_var_opt = _resolve_var_by_substrings(opt_data, ["spend", "spend_amount"])
        inc_var_opt = _resolve_var_by_substrings(
            opt_data, ["incremental_outcome", "incremental", "outcome"]
        )
        inc_var_nonopt = _resolve_var_by_substrings(
            nonopt_data, ["incremental_outcome", "incremental", "outcome"]
        )
        logger.info(
            "Resolved opt vars - spend=%s, inc_opt=%s, inc_nonopt=%s",
            spend_var_opt, inc_var_opt, inc_var_nonopt,
        )
        if not spend_var_opt or not inc_var_opt:
            _dump_ds_diag("optimized_data MISSING expected vars", opt_data)
        if not inc_var_nonopt:
            _dump_ds_diag("nonoptimized_data MISSING expected vars", nonopt_data)

        def _get_opt_val(ds, var_name, channel_name, metric_name="mean"):
            """Extract a scalar from optimization result Dataset."""
            try:
                if not isinstance(ds, xr.Dataset) or var_name is None or var_name not in ds.data_vars:
                    return None
                val = ds[var_name]
                sel_kwargs = {}
                if ch_dim and ch_dim in val.dims:
                    sel_kwargs[ch_dim] = channel_name
                if "metric" in val.dims:
                    sel_kwargs["metric"] = metric_name
                return float(val.sel(**sel_kwargs).values.flat[0])
            except (KeyError, IndexError, ValueError):
                return None

        opt_channel_names = None
        if ch_dim and isinstance(opt_data, xr.Dataset):
            opt_channel_names = list(opt_data.coords[ch_dim].values)
        opt_channel_set = set(map(str, opt_channel_names)) if opt_channel_names else None

        for channel in MODEL_CHANNELS:
            curr = current_spend[channel]

            # Channels not in the optimizer output were dropped from the model.
            # Keep current spend with zero outcome - never borrow a positional
            # neighbour's optimized values. 
            if opt_channel_set is not None and str(channel) not in opt_channel_set:
                results.append(BudgetOptResult(
                    scenario="fixed_budget",
                    channel=channel,
                    current_spend=curr,
                    optimized_spend=curr,
                    current_outcome=0.0,
                    optimized_outcome=0.0,
                    pct_change=0.0,
                ))
                continue

            # Select strictly BY NAME (the helper does .sel(channel=name)).
            opt_ch_name = channel

            # Optimized spend
            opt_val = _get_opt_val(opt_data, spend_var_opt, opt_ch_name, "mean")
            if opt_val is None:
                opt_val = curr

            # Current (non-optimized) outcome
            current_outcome_val = _get_opt_val(nonopt_data, inc_var_nonopt, opt_ch_name, "mean")
            if current_outcome_val is None:
                current_outcome_val = 0.0

            # Optimized outcome
            optimized_outcome_val = _get_opt_val(opt_data, inc_var_opt, opt_ch_name, "mean")
            if optimized_outcome_val is None:
                optimized_outcome_val = 0.0

            pct_change = (
                (opt_val - curr) / curr * 100 if curr > 0 else 0.0
            )

            results.append(BudgetOptResult(
                scenario="fixed_budget",
                channel=channel,
                current_spend=curr,
                optimized_spend=opt_val,
                current_outcome=current_outcome_val,
                optimized_outcome=optimized_outcome_val,
                pct_change=pct_change,
            ))

        logger.info("Budget optimization complete.")

    except Exception as e:
        logger.error("Budget optimization failed: %s", e, exc_info=True)
        # Return current spend as fallback - only for channels the model fit
        # (spend > 0), matching the success path. Dropped channels (paid_search,
        # tv) get no rows rather than phantom $0->$0 entries. 
        for channel in MODEL_CHANNELS:
            curr = current_spend[channel]
            if curr <= 0:
                continue
            results.append(BudgetOptResult(
                scenario="fixed_budget",
                channel=channel,
                current_spend=curr,
                optimized_spend=curr,
                current_outcome=0.0,
                optimized_outcome=0.0,
                pct_change=0.0,
            ))

    return results


def _extract_weekly_contributions(
    az,
    weekly_df,
    weeks: list,
    kpi_type: str,
) -> List[WeeklyContribution]:
    """
    Extract weekly channel-level contributions to the KPI.

    Meridian v1.x:
    - incremental_outcome(aggregate_times=False) returns tensor with time dim
      shape: (n_chains, n_draws, n_times, n_channels) when geos aggregated
    - expected_outcome(aggregate_times=False) returns tensor with time dim
      shape: (n_chains, n_draws, n_times) when geos aggregated
    """
    logger.info("Extracting weekly contributions...")

    kpi_config = KPI_CONFIGS[kpi_type]
    kpi_col = kpi_config.column
    results = []

    # Model channel order (zero-spend channels are dropped by data_prep), used
    # to map MODEL_CHANNELS -> the contributions tensor channel dim BY NAME.
    # Indexing this tensor positionally by MODEL_CHANNELS index mislabels every
    # channel after the first dropped one. 
    active_order = [
        ch for ch in MODEL_CHANNELS
        if float(weekly_df.loc[weekly_df["channel"] == ch, "spend"].sum()) > 0
    ]
    active_pos = {ch: i for i, ch in enumerate(active_order)}

    # Get incremental outcome per time per channel (not aggregated over time)
    contributions = None
    try:
        contrib_tensor = az.incremental_outcome(
            aggregate_geos=True,
            aggregate_times=False,
        )
        # If Meridian returned a Dataset (some versions wrap the tensor), pull
        # out the incremental_outcome var. Otherwise treat as numpy.
        if isinstance(contrib_tensor, xr.Dataset):
            inc_v = _resolve_var_by_substrings(
                contrib_tensor, ["incremental_outcome", "incremental", "outcome"]
            )
            if inc_v is None:
                _dump_ds_diag("weekly incremental_outcome (Dataset, no var)", contrib_tensor)
            else:
                contributions = np.asarray(contrib_tensor[inc_v].values)
        else:
            contributions = np.asarray(contrib_tensor)
        logger.info(
            "incremental_outcome(aggregate_times=False) shape: %s, dtype: %s",
            getattr(contributions, "shape", "?"),
            getattr(contributions, "dtype", "?"),
        )
    except Exception as e:
        logger.error("Failed to extract weekly incremental_outcome: %s", e)

    # Get predicted outcome per time (not aggregated over time)
    predicted = None
    try:
        pred_tensor = az.expected_outcome(
            aggregate_geos=True,
            aggregate_times=False,
        )
        if isinstance(pred_tensor, xr.Dataset):
            pred_v = _resolve_var_by_substrings(
                pred_tensor, ["expected_outcome", "expected", "outcome", "predicted"]
            )
            if pred_v is None:
                _dump_ds_diag("weekly expected_outcome (Dataset, no var)", pred_tensor)
            else:
                predicted = np.asarray(pred_tensor[pred_v].values)
        else:
            predicted = np.asarray(pred_tensor)
        logger.info(
            "expected_outcome(aggregate_times=False) shape: %s",
            getattr(predicted, "shape", "?"),
        )
    except Exception as e:
        logger.error("Failed to extract weekly expected_outcome: %s", e)

    # Compute actual KPI per week
    kpi_by_week = (
        weekly_df.groupby("week_start")[kpi_col]
        .sum()
        .to_dict()
    )

    for t_idx, week in enumerate(weeks):
        actual_kpi = float(kpi_by_week.get(week, 0.0))

        # Predicted KPI for this week - average across chains/draws
        pred_val = 0.0
        if predicted is not None:
            arr = predicted
            try:
                if arr.ndim == 1 and t_idx < len(arr):
                    pred_val = float(arr[t_idx])
                elif arr.ndim == 2 and t_idx < arr.shape[-1]:
                    # (chains*draws, n_times) or (n_draws, n_times)
                    pred_val = float(np.mean(arr[:, t_idx]))
                elif arr.ndim == 3 and t_idx < arr.shape[-1]:
                    # (n_chains, n_draws, n_times)
                    pred_val = float(np.mean(arr[:, :, t_idx]))
                elif arr.ndim >= 2 and t_idx < arr.shape[-2]:
                    # Generic: assume time is second-to-last dim
                    pred_val = float(np.mean(arr[..., t_idx, :] if arr.shape[-1] != len(weeks) else arr[..., t_idx]))
            except (IndexError, TypeError):
                pred_val = 0.0

        for channel in MODEL_CHANNELS:
            contrib_val = 0.0
            # Channel position in the tensor's (active-ordered) channel dim,
            # resolved BY NAME. None => channel was dropped => genuine 0.
            cidx = active_pos.get(channel)
            if contributions is not None and cidx is not None:
                arr = contributions
                try:
                    # Expected shapes after aggregation:
                    # (n_chains, n_draws, n_times, n_channels) - most likely
                    # (n_draws, n_times, n_channels) - if chains flattened
                    # (n_times, n_channels) - if samples already averaged
                    if arr.ndim == 4 and t_idx < arr.shape[2] and cidx < arr.shape[3]:
                        contrib_val = float(np.mean(arr[:, :, t_idx, cidx]))
                    elif arr.ndim == 3 and t_idx < arr.shape[1] and cidx < arr.shape[2]:
                        contrib_val = float(np.mean(arr[:, t_idx, cidx]))
                    elif arr.ndim == 2 and t_idx < arr.shape[0] and cidx < arr.shape[1]:
                        contrib_val = float(arr[t_idx, cidx])
                except (IndexError, TypeError):
                    contrib_val = 0.0

            week_str = (
                week.strftime("%Y-%m-%d")
                if hasattr(week, "strftime")
                else str(week)[:10]
            )

            results.append(WeeklyContribution(
                week_start=week_str,
                channel=channel,
                contribution=contrib_val,
                actual_kpi=actual_kpi,
                predicted_kpi=pred_val,
            ))

    logger.info("Extracted %d weekly contribution rows.", len(results))
    return results


# =============================================================================
# Public API
# =============================================================================

def run_model(
    input_data,
    weekly_df,
    weeks: list,
    kpi_type: str,
    params: ModelHyperparameters = MODEL_PARAMS,
) -> ModelResults:
    """
    Full model pipeline: fit model, extract all results.

    Args:
        input_data: Meridian InputData object
        weekly_df: Weekly aggregated DataFrame
        weeks: List of week_start dates
        kpi_type: KPI type key (e.g. "lc_revenue")
        params: Model hyperparameters

    Returns:
        ModelResults with all extracted metrics
    """
    # Fit the model
    model = fit_model(input_data, params)

    # Extract results
    results = extract_results(model, weekly_df, weeks, kpi_type, params)

    return results
