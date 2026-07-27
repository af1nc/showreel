"""
Data preparation for the spend -> brand-demand -> revenue lag model.

In the original production system this module queried a data warehouse,
mapped raw channels, and aggregated spend, a brand-demand signal, and
revenue to weekly panels per market. That warehouse dependency has been
stubbed for this standalone version: instead we generate a deterministic
synthetic CSV and read it back, then z-score standardise every numeric
column before the VAR stage.

Public functions:
    generate_sample_csv(...)  -> write a deterministic weekly panel CSV
    load_market_weekly(...)   -> read the CSV into a DataFrame
    split_by_market(...)      -> dict of market -> weekly DataFrame
    standardize_market_data() -> z-score each column, degrade gracefully
    prepare_data(...)         -> end-to-end: load, filter, standardise
"""

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from config import (
    CHANNEL_SPEND_COLUMNS,
    DEMAND_SIGNAL_COLUMN,
    MIN_WEEKS,
    NUMERIC_COLUMNS,
    REVENUE_COLUMN,
    SAMPLE_CSV,
    TOTAL_SPEND_COLUMN,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Synthetic sample generation (warehouse stub)
# =============================================================================

# Each market has its own profile. `signal=True` markets carry a genuine
# lagged spend -> brand_search -> revenue chain. The one `signal=False`
# market has a flat (zero-variance) demand signal, which exercises the
# model's graceful fall-back from a 3-variable to a 2-variable VAR.
_MARKET_PROFILES: List[dict] = [
    {
        "market": "market_alpha",
        "signal": True,
        "base_spend": 42000.0,
        "shares": [0.35, 0.25, 0.22, 0.18],
        "search_base": 32.0,
        "a2": 0.00042,   # brand_search response to spend at lag 2
        "a3": 0.00030,   # brand_search response to spend at lag 3
        "search_noise": 3.5,
        "rev_base": 55000.0,
        "b1": 3100.0,    # revenue response to brand_search at lag 1
        "b2": 2100.0,    # revenue response to brand_search at lag 2
        "direct": 0.45,  # small direct revenue response to spend at lag 4
        "rev_noise": 14000.0,
    },
    {
        "market": "market_beta",
        "signal": True,
        "base_spend": 28000.0,
        "shares": [0.28, 0.30, 0.24, 0.18],
        "search_base": 25.0,
        "a2": 0.00055,
        "a3": 0.00025,
        "search_noise": 3.0,
        "rev_base": 38000.0,
        "b1": 2600.0,
        "b2": 1700.0,
        "direct": 0.35,
        "rev_noise": 11000.0,
    },
    {
        "market": "market_gamma",
        "signal": True,
        "base_spend": 61000.0,
        "shares": [0.40, 0.20, 0.20, 0.20],
        "search_base": 45.0,
        "a2": 0.00030,
        "a3": 0.00038,
        "search_noise": 4.0,
        "rev_base": 72000.0,
        "b1": 3600.0,
        "b2": 2400.0,
        "direct": 0.55,
        "rev_noise": 18000.0,
    },
    {
        "market": "market_delta",
        "signal": False,   # no demand signal available -> zero-variance column
        "base_spend": 33000.0,
        "shares": [0.30, 0.28, 0.22, 0.20],
        "search_base": 0.0,
        "a2": 0.0,
        "a3": 0.0,
        "search_noise": 0.0,
        "rev_base": 41000.0,
        "b1": 0.0,
        "b2": 0.0,
        "direct": 0.85,    # revenue still responds to spend directly (lag 4)
        "rev_noise": 12000.0,
    },
]


def _build_market_frame(
    spec: dict,
    n_weeks: int,
    rng: np.random.Generator,
    week_starts: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build one market's weekly panel with a believable lagged structure."""
    channels = list(CHANNEL_SPEND_COLUMNS.values())
    weeks = np.arange(n_weeks)
    season = np.sin(2.0 * np.pi * weeks / 52.0)

    # Total spend: seasonal level plus a persistent (AR-1) noise term, kept
    # positive. The channels are then carved out of this total.
    innovations = rng.normal(0.0, 0.15, n_weeks)
    ar = np.zeros(n_weeks)
    for t in range(1, n_weeks):
        ar[t] = 0.5 * ar[t - 1] + innovations[t]
    base = spec["base_spend"]
    latent_total = np.clip(base * (1.0 + 0.35 * season + ar), base * 0.10, None)

    # Split the latent total into channels, adding mild per-channel jitter,
    # then set total_spend to the exact sum of channels for consistency.
    channel_series: Dict[str, np.ndarray] = {}
    for col, share in zip(channels, spec["shares"]):
        jitter = 1.0 + rng.normal(0.0, 0.05, n_weeks)
        channel_series[col] = np.clip(latent_total * share * jitter, 0.0, None)
    total_spend = np.sum(list(channel_series.values()), axis=0)

    # Brand-demand signal: responds to spend at lags 2 and 3 (or is flat when
    # this market has no signal, which forces the 2-variable VAR fall-back).
    if spec["signal"]:
        search_noise = rng.normal(0.0, spec["search_noise"], n_weeks)
        brand_search = np.full(n_weeks, spec["search_base"], dtype=float)
        for t in range(n_weeks):
            if t >= 2:
                brand_search[t] += spec["a2"] * total_spend[t - 2]
            if t >= 3:
                brand_search[t] += spec["a3"] * total_spend[t - 3]
            brand_search[t] += search_noise[t]
        brand_search = np.clip(brand_search, 0.0, None)
    else:
        brand_search = np.zeros(n_weeks)

    # Revenue: responds to the demand signal at lags 1 and 2, plus a small
    # direct response to spend at lag 4.
    rev_noise = rng.normal(0.0, spec["rev_noise"], n_weeks)
    revenue = np.full(n_weeks, spec["rev_base"], dtype=float)
    for t in range(n_weeks):
        if t >= 1:
            revenue[t] += spec["b1"] * brand_search[t - 1]
        if t >= 2:
            revenue[t] += spec["b2"] * brand_search[t - 2]
        if t >= 4:
            revenue[t] += spec["direct"] * total_spend[t - 4]
        revenue[t] += rev_noise[t]
    revenue = np.clip(revenue, 0.0, None)

    frame = pd.DataFrame({
        "market": spec["market"],
        "week_start": week_starts,
        TOTAL_SPEND_COLUMN: np.round(total_spend, 2),
    })
    for col in channels:
        frame[col] = np.round(channel_series[col], 2)
    frame[DEMAND_SIGNAL_COLUMN] = np.round(brand_search, 2)
    frame[REVENUE_COLUMN] = np.round(revenue, 2)
    return frame


def generate_sample_csv(
    path: Path = SAMPLE_CSV,
    n_weeks: int = 156,
    seed: int = 20240501,
    start_date: str = "2021-01-04",
) -> pd.DataFrame:
    """
    Generate a deterministic weekly panel and write it to `path`.

    The panel spans several generic markets over `n_weeks` weeks. Given the
    same seed it always produces identical numbers, so results are
    reproducible. Returns the combined DataFrame.
    """
    rng = np.random.default_rng(seed)
    week_starts = pd.date_range(start=start_date, periods=n_weeks, freq="7D")

    frames = [
        _build_market_frame(spec, n_weeks, rng, week_starts)
        for spec in _MARKET_PROFILES
    ]
    combined = pd.concat(frames, ignore_index=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info(
        "Wrote synthetic sample: %d rows, %d markets -> %s",
        len(combined), combined["market"].nunique(), path,
    )
    return combined


# =============================================================================
# Loading and per-market split
# =============================================================================

def load_market_weekly(path: Path = SAMPLE_CSV) -> pd.DataFrame:
    """Read the weekly panel CSV, generating it first if it is missing."""
    if not Path(path).exists():
        logger.info("Sample CSV not found at %s, generating it.", path)
        generate_sample_csv(path)

    df = pd.read_csv(path, parse_dates=["week_start"])
    logger.info(
        "Loaded %d rows across %d markets from %s",
        len(df), df["market"].nunique(), path,
    )
    return df


def split_by_market(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Split the panel into one time-ordered DataFrame per market."""
    market_data: Dict[str, pd.DataFrame] = {}
    for market, group in df.groupby("market"):
        ordered = group.sort_values("week_start").reset_index(drop=True)
        market_data[str(market)] = ordered
    return market_data


def filter_markets(
    market_data: Dict[str, pd.DataFrame],
    min_weeks: int = MIN_WEEKS,
) -> Dict[str, pd.DataFrame]:
    """Keep only markets with at least `min_weeks` of data."""
    kept: Dict[str, pd.DataFrame] = {}
    for market, df in market_data.items():
        if len(df) >= min_weeks:
            kept[market] = df
        else:
            logger.warning(
                "Market %s has only %d weeks (< %d), skipping.",
                market, len(df), min_weeks,
            )
    return kept


# =============================================================================
# Z-score standardisation (with graceful zero-variance handling)
# =============================================================================

def standardize_market_data(
    market_data: Dict[str, pd.DataFrame],
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Dict[str, Tuple[float, float]]]]:
    """
    Z-score standardise every numeric column for VAR modelling.

    A constant column (zero variance) cannot be scaled, so its std is set to
    1.0 and the centred values remain flat. Downstream the model detects this
    flat column and falls back from a 3-variable to a 2-variable VAR.

    Returns:
        standardized: dict of market -> standardised DataFrame
        stats: dict of market -> {column: (mean, std)} for de-standardising
    """
    standardized: Dict[str, pd.DataFrame] = {}
    stats: Dict[str, Dict[str, Tuple[float, float]]] = {}

    for market, df in market_data.items():
        df_std = df.copy()
        market_stats: Dict[str, Tuple[float, float]] = {}

        for col in NUMERIC_COLUMNS:
            mean = df[col].mean()
            std = df[col].std()

            # Avoid division by zero for constant columns.
            if std < 1e-10:
                logger.warning(
                    "Market %s: column %s has near-zero std (%.6f), "
                    "leaving it centred and flat.",
                    market, col, std,
                )
                std = 1.0

            df_std[col] = (df[col] - mean) / std
            market_stats[col] = (float(mean), float(std))

        standardized[market] = df_std
        stats[market] = market_stats

    logger.info("Standardised %d markets.", len(standardized))
    return standardized, stats


# =============================================================================
# End-to-end preparation
# =============================================================================

def prepare_data(
    path: Path = SAMPLE_CSV,
    min_weeks: int = MIN_WEEKS,
) -> Tuple[
    Dict[str, pd.DataFrame],
    Dict[str, pd.DataFrame],
    Dict[str, Dict[str, Tuple[float, float]]],
]:
    """
    Load the CSV, split by market, drop thin markets, and standardise.

    Returns:
        raw_market_data: dict of market -> raw (unstandardised) DataFrame
        std_market_data: dict of market -> standardised DataFrame
        std_stats:       dict of market -> {column: (mean, std)}
    """
    df = load_market_weekly(path)
    raw_market_data = filter_markets(split_by_market(df), min_weeks=min_weeks)
    std_market_data, std_stats = standardize_market_data(raw_market_data)
    return raw_market_data, std_market_data, std_stats
