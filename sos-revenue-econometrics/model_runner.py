"""
VAR / Granger causality runner for the spend -> brand-demand -> revenue lag pipeline.

For each market:
1. Granger causality tests: spend -> brand_search, brand_search -> revenue, spend -> revenue
2. VAR model fitting with AIC-based lag selection
3. Impulse Response Function (IRF) extraction with bootstrap CIs
4. Per-channel IRFs (which channels drive the demand signal vs revenue most)
5. Lag structure extraction (optimal lag, peak response, cumulative effect, half-life)

The econometrics run entirely on statsmodels and scipy.
"""

import logging
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats  # noqa: F401  (kept for downstream extension)
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import grangercausalitytests

from config import (
    CHANNEL_SPEND_COLUMNS,
    IRF_BOOTSTRAP_REPS,
    IRF_CI_ALPHA,
    IRF_HORIZON,
    MAX_LAG_WEEKS,
    SIGNIFICANCE_LEVEL,
)

logger = logging.getLogger(__name__)

# Suppress convergence warnings from statsmodels during the AIC search.
warnings.filterwarnings("ignore", category=UserWarning, module="statsmodels")


# =============================================================================
# Result Data Classes
# =============================================================================

@dataclass
class GrangerResult:
    """Result of a single Granger causality test."""
    market: str
    direction: str          # "spend_to_brand_search", "brand_search_to_revenue", "spend_to_revenue"
    lag_weeks: int
    f_statistic: float
    p_value: float
    significant: bool


@dataclass
class ImpulseResponseResult:
    """Result of a single impulse response at a given horizon."""
    market: str
    impulse_variable: str   # "total_spend", "display_spend", etc.
    response_variable: str  # "brand_search", "revenue"
    horizon_weeks: int
    response: float
    response_lower: float
    response_upper: float


@dataclass
class LagStructureResult:
    """Extracted lag structure for a variable pair."""
    market: str
    variable_pair: str      # "spend->brand_search", "brand_search->revenue", "spend->revenue"
    optimal_lag_weeks: int
    peak_response_week: int
    total_cumulative_effect: float
    half_life_weeks: float


@dataclass
class MarketResults:
    """All results for a single market."""
    market: str
    granger: List[GrangerResult] = field(default_factory=list)
    impulse_responses: List[ImpulseResponseResult] = field(default_factory=list)
    lag_structure: List[LagStructureResult] = field(default_factory=list)
    var_lag_order: int = 0
    var_aic: float = 0.0
    error: Optional[str] = None


# =============================================================================
# Granger Causality Tests
# =============================================================================

def run_granger_tests(
    df: pd.DataFrame,
    market: str,
    max_lag: int = MAX_LAG_WEEKS,
) -> List[GrangerResult]:
    """
    Run Granger causality tests for 3 directions:
    1. total_spend -> brand_search
    2. brand_search -> revenue
    3. total_spend -> revenue

    Tests lags 1 through max_lag. Returns F-stat and p-value at each lag.
    """
    results: List[GrangerResult] = []

    test_pairs = [
        ("spend_to_brand_search", "brand_search", "total_spend"),
        ("brand_search_to_revenue", "revenue", "brand_search"),
        ("spend_to_revenue", "revenue", "total_spend"),
    ]

    for direction, y_col, x_col in test_pairs:
        try:
            # grangercausalitytests expects [y, x]: tests if x Granger-causes y.
            test_data = df[[y_col, x_col]].dropna().values

            if len(test_data) < max_lag + 5:
                logger.warning(
                    "Market %s: insufficient data for Granger test %s "
                    "(%d rows, need %d)",
                    market, direction, len(test_data), max_lag + 5,
                )
                continue

            # Run Granger tests at all lags.
            gc_results = grangercausalitytests(
                test_data,
                maxlag=max_lag,
                verbose=False,
            )

            for lag in range(1, max_lag + 1):
                # Extract F-test results (ssr_ftest).
                f_stat = gc_results[lag][0]["ssr_ftest"][0]
                p_value = gc_results[lag][0]["ssr_ftest"][1]

                results.append(GrangerResult(
                    market=market,
                    direction=direction,
                    lag_weeks=lag,
                    f_statistic=float(f_stat),
                    p_value=float(p_value),
                    significant=p_value < SIGNIFICANCE_LEVEL,
                ))

        except Exception as e:
            logger.warning(
                "Market %s: Granger test failed for %s: %s",
                market, direction, e,
            )

    sig_count = sum(1 for r in results if r.significant)
    logger.info(
        "Market %s: %d Granger tests, %d significant (p < %.2f)",
        market, len(results), sig_count, SIGNIFICANCE_LEVEL,
    )

    return results


# =============================================================================
# VAR Model Fitting
# =============================================================================

def _has_zero_variance(df: pd.DataFrame, col: str) -> bool:
    """Check if a column has zero or near-zero variance (e.g. all constant)."""
    return df[col].std() < 1e-10


def fit_var_model(
    df: pd.DataFrame,
    columns: List[str],
    max_lag: int = MAX_LAG_WEEKS,
) -> Tuple[Optional[object], int, float]:
    """
    Fit a VAR model on the specified columns, selecting the optimal lag via AIC.

    Returns:
        var_result: fitted VARResults object (or None on failure)
        optimal_lag: selected lag order
        aic: AIC value at the optimal lag
    """
    data = df[columns].dropna().values

    if len(data) < max_lag + 10:
        logger.warning(
            "Insufficient data for VAR (%d rows, need %d)",
            len(data), max_lag + 10,
        )
        return None, 0, 0.0

    try:
        model = VAR(data)

        # Select the optimal lag order via AIC.
        # Limit to max_lag or a data-driven maximum.
        max_possible_lag = min(max_lag, len(data) // 3)
        if max_possible_lag < 1:
            max_possible_lag = 1

        lag_order = model.select_order(maxlags=max_possible_lag)
        optimal_lag = lag_order.aic
        if optimal_lag < 1:
            optimal_lag = 1

        # Fit the model at the optimal lag.
        var_result = model.fit(maxlags=optimal_lag)
        aic = var_result.aic

        return var_result, optimal_lag, aic

    except np.linalg.LinAlgError as e:
        logger.warning(
            "VAR fitting failed (singular matrix, likely a zero-variance column): %s",
            e,
        )
        return None, 0, 0.0
    except ValueError as e:
        logger.warning("VAR fitting failed (ValueError): %s", e)
        return None, 0, 0.0
    except Exception as e:
        logger.warning("VAR fitting failed: %s", e)
        return None, 0, 0.0


def extract_irf(
    var_result: object,
    columns: List[str],
    impulse_col: str,
    response_col: str,
    market: str,
    horizon: int = IRF_HORIZON,
    n_boot: int = IRF_BOOTSTRAP_REPS,
    alpha: float = IRF_CI_ALPHA,
) -> List[ImpulseResponseResult]:
    """
    Extract an impulse response function from a fitted VAR model.

    Computes the response of response_col to a 1-std-dev shock in impulse_col,
    with Monte-Carlo bootstrap confidence intervals.

    Returns a list of ImpulseResponseResult for each horizon step.
    """
    results: List[ImpulseResponseResult] = []

    try:
        impulse_idx = columns.index(impulse_col)
        response_idx = columns.index(response_col)
    except ValueError as e:
        logger.warning(
            "[%s] Column not found in VAR for %s -> %s: %s (columns=%s)",
            market, impulse_col, response_col, e, columns,
        )
        return results

    try:
        # Compute the IRF.
        irf = var_result.irf(periods=horizon)

        # Point estimates.
        irf_values = irf.irfs[:, response_idx, impulse_idx]

        # Bootstrap confidence intervals.
        try:
            irf_err = irf.errband_mc(
                orth=False,
                repl=n_boot,
                signif=alpha,
            )
            # statsmodels returns the band either as a (lower, upper) tuple of
            # (periods, neqs, neqs) arrays, or as a single stacked
            # (periods, neqs, neqs, 2) array. Support both.
            if isinstance(irf_err, tuple):
                lower_band, upper_band = irf_err
                lower = np.asarray(lower_band)[:, response_idx, impulse_idx]
                upper = np.asarray(upper_band)[:, response_idx, impulse_idx]
            else:
                lower = irf_err[:, response_idx, impulse_idx, 0]
                upper = irf_err[:, response_idx, impulse_idx, 1]
        except Exception:
            # Fall back to an asymptotic-style band if the bootstrap fails.
            logger.info(
                "Bootstrap CIs failed for %s -> %s in %s, "
                "using +/- 1.645 * point estimate as a proxy band.",
                impulse_col, response_col, market,
            )
            lower = irf_values - 1.645 * np.abs(irf_values) * 0.5
            upper = irf_values + 1.645 * np.abs(irf_values) * 0.5

        # Map the internal column name to a standard variable name.
        impulse_name = _standardize_impulse_name(impulse_col)
        response_name = _standardize_response_name(response_col)

        for h in range(horizon + 1):
            results.append(ImpulseResponseResult(
                market=market,
                impulse_variable=impulse_name,
                response_variable=response_name,
                horizon_weeks=h,
                response=float(irf_values[h]) if h < len(irf_values) else 0.0,
                response_lower=float(lower[h]) if h < len(lower) else 0.0,
                response_upper=float(upper[h]) if h < len(upper) else 0.0,
            ))

    except Exception as e:
        # Use logger.exception to surface the full traceback. IRF failures are
        # otherwise easy to miss: a market can produce Granger rows but no IRF
        # rows, and a one-line warning makes that asymmetry hard to diagnose.
        logger.exception(
            "[%s] IRF extraction failed for %s -> %s: %s",
            market, impulse_col, response_col, e,
        )

    return results


def _standardize_impulse_name(col: str) -> str:
    """Map an internal column name to a standard impulse variable name."""
    name_map = {
        "total_spend": "total_spend",
        "search_spend": "search_spend",
        "social_spend": "social_spend",
        "display_spend": "display_spend",
        "video_spend": "video_spend",
        "brand_search": "brand_search",
    }
    return name_map.get(col, col)


def _standardize_response_name(col: str) -> str:
    """Map an internal column name to a standard response variable name."""
    name_map = {
        "brand_search": "brand_search",
        "revenue": "revenue",
    }
    return name_map.get(col, col)


# =============================================================================
# Lag Structure Extraction
# =============================================================================

def extract_lag_structure(
    granger_results: List[GrangerResult],
    irf_results: List[ImpulseResponseResult],
    market: str,
) -> List[LagStructureResult]:
    """
    Extract the lag structure for each variable pair:
    - Optimal lag: lag with the max Granger F-statistic
    - Peak response week: week with the max absolute IRF
    - Cumulative effect: sum of all IRF values
    - Half-life: weeks to reach 50% of the cumulative effect

    Variable pairs:
    - spend->brand_search (total_spend impulse, brand_search response)
    - brand_search->revenue (brand_search impulse, revenue response)
    - spend->revenue (total_spend impulse, revenue response)
    """
    results: List[LagStructureResult] = []

    pair_defs = [
        ("spend->brand_search", "spend_to_brand_search", "total_spend", "brand_search"),
        ("brand_search->revenue", "brand_search_to_revenue", "brand_search", "revenue"),
        ("spend->revenue", "spend_to_revenue", "total_spend", "revenue"),
    ]

    for pair_label, granger_dir, impulse_var, response_var in pair_defs:
        try:
            # Find the optimal lag from the Granger tests (max F-statistic).
            pair_granger = [
                g for g in granger_results
                if g.direction == granger_dir and g.market == market
            ]

            if not pair_granger:
                logger.info(
                    "Market %s: no Granger results for %s, skipping.",
                    market, pair_label,
                )
                continue

            best_granger = max(pair_granger, key=lambda g: g.f_statistic)
            optimal_lag = best_granger.lag_weeks

            # Find the IRF values for this pair.
            pair_irf = [
                r for r in irf_results
                if r.market == market
                and r.impulse_variable == impulse_var
                and r.response_variable == response_var
            ]

            if not pair_irf:
                logger.info(
                    "Market %s: no IRF results for %s, skipping lag structure.",
                    market, pair_label,
                )
                continue

            # Sort by horizon.
            pair_irf.sort(key=lambda r: r.horizon_weeks)
            responses = [r.response for r in pair_irf]

            # Peak response week (max absolute response).
            abs_responses = [abs(r) for r in responses]
            peak_week = int(np.argmax(abs_responses))

            # Cumulative effect (sum of all IRF values).
            cumulative = sum(responses)

            # Half-life: weeks to reach 50% of the cumulative effect.
            half_life = _compute_half_life(responses)

            results.append(LagStructureResult(
                market=market,
                variable_pair=pair_label,
                optimal_lag_weeks=optimal_lag,
                peak_response_week=peak_week,
                total_cumulative_effect=float(cumulative),
                half_life_weeks=float(half_life),
            ))

            logger.info(
                "Market %s, %s: optimal_lag=%d, peak_week=%d, "
                "cumulative=%.4f, half_life=%.1f",
                market, pair_label, optimal_lag, peak_week,
                cumulative, half_life,
            )

        except Exception as e:
            logger.warning(
                "Market %s: lag structure extraction failed for %s: %s",
                market, pair_label, e,
            )

    return results


def _compute_half_life(responses: List[float]) -> float:
    """
    Compute the half-life: number of weeks to reach 50% of the total
    cumulative effect.

    Handles both positive and negative cumulative effects. If the cumulative
    effect is effectively zero, returns 0.
    """
    total = sum(responses)
    if abs(total) < 1e-10:
        return 0.0

    running_sum = 0.0
    half_target = total * 0.5

    for i, r in enumerate(responses):
        running_sum += r
        # Handle both positive and negative cumulative effects.
        if total > 0 and running_sum >= half_target:
            return float(i)
        elif total < 0 and running_sum <= half_target:
            return float(i)

    return float(len(responses))


# =============================================================================
# Per-Market Model Runner
# =============================================================================

def run_market_model(
    market: str,
    std_df: pd.DataFrame,
) -> MarketResults:
    """
    Run the full model pipeline for a single market:
    1. Granger causality tests (3 directions, lags 1-12)
    2. Core VAR model: [total_spend, brand_search, revenue]
       - If brand_search has zero variance (no demand signal), fall back to a
         reduced 2-variable VAR: [total_spend, revenue]
    3. Per-channel VARs: [channel_spend, brand_search, revenue]
       - Same fall-back to [channel_spend, revenue] if no demand signal
    4. Lag structure extraction
    """
    logger.info("=" * 50)
    logger.info("MODELLING MARKET: %s", market)
    logger.info("=" * 50)

    result = MarketResults(market=market)

    # Determine whether this market has an active demand signal (non-zero variance).
    has_signal = not _has_zero_variance(std_df, "brand_search")
    if has_signal:
        logger.info("[%s] Has demand signal (brand_search variance > 0)", market)
    else:
        logger.info(
            "[%s] No demand signal (brand_search is flat), "
            "will run a reduced VAR without brand_search.",
            market,
        )

    try:
        # =====================================================================
        # Step 1: Granger Causality Tests
        # =====================================================================
        logger.info("[%s] Running Granger causality tests...", market)
        result.granger = run_granger_tests(std_df, market)

        # =====================================================================
        # Step 2: Core VAR Model
        # =====================================================================
        if has_signal:
            # Full 3-variable VAR: [total_spend, brand_search, revenue].
            logger.info("[%s] Fitting core VAR model (3-var with signal)...", market)
            core_cols = ["total_spend", "brand_search", "revenue"]
        else:
            # Reduced 2-variable VAR: [total_spend, revenue].
            logger.info("[%s] Fitting core VAR model (2-var, no signal)...", market)
            core_cols = ["total_spend", "revenue"]

        var_result, lag_order, aic = fit_var_model(std_df, core_cols)

        if var_result is None:
            # If the 3-var model failed, try the reduced 2-var as a fall-back.
            if has_signal:
                logger.warning(
                    "[%s] 3-var core VAR failed, falling back to 2-var "
                    "[total_spend, revenue]...",
                    market,
                )
                core_cols = ["total_spend", "revenue"]
                var_result, lag_order, aic = fit_var_model(std_df, core_cols)

            if var_result is None:
                result.error = "Core VAR model failed to fit"
                logger.error("[%s] Core VAR model failed (even 2-var)", market)
                return result

        result.var_lag_order = lag_order
        result.var_aic = aic
        logger.info(
            "[%s] Core VAR: columns=%s, lag_order=%d, AIC=%.4f",
            market, core_cols, lag_order, aic,
        )

        # Extract IRFs from the core model.
        if has_signal and "brand_search" in core_cols:
            # Full 3-var: extract all 3 IRF directions.
            # total_spend -> brand_search
            result.impulse_responses.extend(
                extract_irf(var_result, core_cols, "total_spend", "brand_search", market)
            )
            # brand_search -> revenue
            result.impulse_responses.extend(
                extract_irf(var_result, core_cols, "brand_search", "revenue", market)
            )

        # total_spend -> revenue (always extracted, from whichever model fitted).
        result.impulse_responses.extend(
            extract_irf(var_result, core_cols, "total_spend", "revenue", market)
        )

        # =====================================================================
        # Step 3: Per-Channel VAR Models
        # =====================================================================
        logger.info("[%s] Fitting per-channel VAR models...", market)

        for channel, spend_col in CHANNEL_SPEND_COLUMNS.items():
            # Check if this channel has meaningful spend.
            if std_df[spend_col].abs().sum() < 1e-6:
                logger.info(
                    "[%s] Skipping channel %s (no spend)", market, channel,
                )
                continue

            if has_signal and "brand_search" in core_cols:
                ch_cols = [spend_col, "brand_search", "revenue"]
            else:
                ch_cols = [spend_col, "revenue"]

            ch_var_result, ch_lag, ch_aic = fit_var_model(std_df, ch_cols)

            # Fall-back: if the 3-var channel VAR failed, try the 2-var.
            if ch_var_result is None and "brand_search" in ch_cols:
                logger.info(
                    "[%s] Channel %s 3-var VAR failed, trying 2-var...",
                    market, channel,
                )
                ch_cols = [spend_col, "revenue"]
                ch_var_result, ch_lag, ch_aic = fit_var_model(std_df, ch_cols)

            if ch_var_result is None:
                logger.info(
                    "[%s] Channel %s VAR failed to fit", market, channel,
                )
                continue

            logger.info(
                "[%s] Channel %s VAR: columns=%s, lag=%d, AIC=%.4f",
                market, channel, ch_cols, ch_lag, ch_aic,
            )

            # Channel spend -> demand signal (only if the signal is in the model).
            if "brand_search" in ch_cols:
                result.impulse_responses.extend(
                    extract_irf(
                        ch_var_result, ch_cols,
                        spend_col, "brand_search", market,
                    )
                )

            # Channel spend -> revenue.
            result.impulse_responses.extend(
                extract_irf(
                    ch_var_result, ch_cols,
                    spend_col, "revenue", market,
                )
            )

        # =====================================================================
        # Step 4: Lag Structure Extraction
        # =====================================================================
        logger.info("[%s] Extracting lag structure...", market)
        result.lag_structure = extract_lag_structure(
            result.granger,
            result.impulse_responses,
            market,
        )

        logger.info(
            "[%s] Computed %d IRF rows across core + per-channel VARs",
            market, len(result.impulse_responses),
        )
        logger.info(
            "[%s] Model complete: %d Granger tests, %d IRF points, "
            "%d lag structures (has_signal=%s)",
            market,
            len(result.granger),
            len(result.impulse_responses),
            len(result.lag_structure),
            has_signal,
        )

        # Surface the Granger-vs-IRF asymmetry that would otherwise be silent:
        # if Granger ran but every IRF extraction returned empty, this market's
        # impulse-response output will be empty even though it "succeeded".
        if len(result.granger) > 0 and len(result.impulse_responses) == 0:
            logger.warning(
                "[%s] WARNING: %d Granger rows but 0 IRF rows, every IRF "
                "extraction returned empty. Check earlier logs for VAR-fit "
                "failures or extract_irf exceptions.",
                market, len(result.granger),
            )

    except Exception as e:
        result.error = str(e)
        logger.error(
            "[%s] Model run failed: %s", market, e, exc_info=True,
        )

    return result


# =============================================================================
# Public API
# =============================================================================

def run_all_markets(
    std_market_data: Dict[str, pd.DataFrame],
) -> Dict[str, MarketResults]:
    """
    Run the model pipeline for all markets.

    Args:
        std_market_data: dict of market -> standardised DataFrame

    Returns:
        dict of market -> MarketResults
    """
    logger.info("=" * 60)
    logger.info("RUNNING MODELS FOR %d MARKETS", len(std_market_data))
    logger.info("=" * 60)

    # Log demand-signal availability across all markets.
    markets_with_signal = [
        m for m, df in std_market_data.items()
        if not _has_zero_variance(df, "brand_search")
    ]
    markets_without_signal = [
        m for m, df in std_market_data.items()
        if _has_zero_variance(df, "brand_search")
    ]
    logger.info(
        "Demand-signal availability: %d markets WITH signal, %d markets WITHOUT signal (flat)",
        len(markets_with_signal), len(markets_without_signal),
    )
    if markets_with_signal:
        logger.info("Markets WITH signal: %s", sorted(markets_with_signal))
    if markets_without_signal:
        logger.info(
            "Markets WITHOUT signal (will use reduced VAR): %s",
            sorted(markets_without_signal),
        )

    all_results: Dict[str, MarketResults] = {}

    for i, (market, df) in enumerate(sorted(std_market_data.items()), 1):
        logger.info(
            "Processing market %d/%d: %s (%d weeks)",
            i, len(std_market_data), market, len(df),
        )

        result = run_market_model(market, df)
        all_results[market] = result

        if result.error:
            logger.warning("[%s] Completed with error: %s", market, result.error)
        else:
            logger.info("[%s] Completed successfully", market)

    # Summary.
    success = sum(1 for r in all_results.values() if r.error is None)
    failed = sum(1 for r in all_results.values() if r.error is not None)

    logger.info("=" * 60)
    logger.info(
        "ALL MARKETS COMPLETE: %d success, %d failed, %d total",
        success, failed, len(all_results),
    )
    logger.info("=" * 60)

    return all_results
