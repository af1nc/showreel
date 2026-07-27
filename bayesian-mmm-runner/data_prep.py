"""
Data preparation for the Bayesian MMM runner.

Loads a weekly media CSV, maps raw channels to model channels, aggregates to
weekly totals, merges a brand-demand control signal, validates, and builds a
Meridian ``InputData`` object.

The CSV loader stands in for whatever real source you have (a data warehouse, a
set of platform exports, etc.). Everything downstream of ``load_media_csv`` is
independent of where the rows came from.

Expected CSV columns:
    week                  ISO date (any day of the week; snapped to Monday)
    channel               raw channel label (mapped via CHANNEL_MAP)
    spend                 media spend for that week+channel
    impressions           impressions for that week+channel
    kpi                    the target KPI contribution for that week+channel
    brand_search_control  a weekly brand-demand signal (same value per week)
"""

import logging
from typing import List, Tuple

import numpy as np
import pandas as pd

from config import (
    CHANNEL_MAP,
    DATA_CSV_PATH,
    KPI_CONFIGS,
    MODEL_CHANNELS,
    ModelHyperparameters,
)

logger = logging.getLogger(__name__)


def load_media_csv(csv_path: str = DATA_CSV_PATH) -> pd.DataFrame:
    """Load the weekly media CSV into a DataFrame.

    Renames ``week`` -> ``week_start`` (as datetime) and ``brand_search_control``
    -> ``brand_search`` so the rest of the pipeline uses stable names.
    """
    logger.info("Loading media data from %s", csv_path)
    df = pd.read_csv(csv_path)
    df["week_start"] = pd.to_datetime(df["week"])
    df = df.drop(columns=["week"])
    if "brand_search_control" in df.columns:
        df = df.rename(columns={"brand_search_control": "brand_search"})
    logger.info(
        "Loaded %d rows (%s to %s, %d raw channels)",
        len(df),
        df["week_start"].min().date(),
        df["week_start"].max().date(),
        df["channel"].nunique(),
    )
    return df


def map_channels(df: pd.DataFrame) -> pd.DataFrame:
    """Map raw channel labels to model channels; drop unmapped rows."""
    df = df.copy()
    df["model_channel"] = df["channel"].str.lower().map(CHANNEL_MAP)

    unmapped = df[df["model_channel"].isna()]["channel"].unique()
    if len(unmapped) > 0:
        logger.warning("Dropping %d unmapped channel labels: %s", len(unmapped), list(unmapped))

    df = df[df["model_channel"].notna()].copy()
    df = df.drop(columns=["channel"]).rename(columns={"model_channel": "channel"})
    return df


def aggregate_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to ISO-weekly totals per channel.

    ``spend``/``impressions``/``kpi`` are summed; the weekly ``brand_search``
    control is carried through as a per-week value (mean, since it is identical
    across a week's channel rows).
    """
    df = df.copy()
    df["week_start"] = pd.to_datetime(df["week_start"])
    # Snap to Monday of the ISO week.
    df["week_start"] = df["week_start"] - pd.to_timedelta(df["week_start"].dt.weekday, unit="D")

    agg = {"spend": "sum", "impressions": "sum", "kpi": "sum"}
    if "brand_search" in df.columns:
        agg["brand_search"] = "mean"

    weekly = df.groupby(["week_start", "channel"], as_index=False).agg(agg)
    weekly = weekly.sort_values(["week_start", "channel"]).reset_index(drop=True)

    logger.info(
        "Aggregated to %d weekly channel rows (%d weeks, %d channels)",
        len(weekly),
        weekly["week_start"].nunique(),
        weekly["channel"].nunique(),
    )
    return weekly


def validate_data(weekly_df: pd.DataFrame, kpi_type: str, min_weeks: int = 52) -> None:
    """Validate the weekly data for model fitting; raise on insufficient data."""
    kpi_col = KPI_CONFIGS[kpi_type].column

    if len(weekly_df) == 0:
        raise ValueError("No data after aggregation")

    n_weeks = weekly_df["week_start"].nunique()
    if n_weeks < min_weeks:
        raise ValueError(f"Insufficient data: {n_weeks} weeks (minimum {min_weeks} required)")

    present = set(weekly_df["channel"].unique())
    missing = set(MODEL_CHANNELS) - present
    if missing:
        # Not fatal: these are dropped before fitting and mapped back by name.
        logger.warning("Channels absent from the data (will be dropped): %s", sorted(missing))

    if weekly_df["spend"].sum() <= 0:
        raise ValueError("Total spend is non-positive")
    if weekly_df[kpi_col].sum() <= 0:
        raise ValueError(f"Total {kpi_type} is non-positive")

    logger.info(
        "Validation passed: %.1fM spend, %.1f total %s over %d weeks",
        weekly_df["spend"].sum() / 1e6, weekly_df[kpi_col].sum(), kpi_type, n_weeks,
    )


def build_input_data(
    weekly_df: pd.DataFrame,
    kpi_type: str,
    params: ModelHyperparameters,
):
    """Build a Meridian ``InputData`` object from the weekly DataFrame.

    Uses Meridian's ``DataFrameInputDataBuilder`` with wide-format data (one row
    per week, one spend/impressions column per channel). A brand-demand signal is
    added as a control variable when present.

    Returns ``(input_data, weeks)`` where ``weeks`` is the ordered list of
    week-start dates used for output alignment.
    """
    from meridian.data import data_frame_input_data_builder as dfb

    kpi_config = KPI_CONFIGS[kpi_type]
    kpi_col = kpi_config.column

    weeks = sorted(weekly_df["week_start"].unique())

    # KPI per week (national aggregate across channels).
    kpi_weekly = (
        weekly_df.groupby("week_start")[kpi_col]
        .sum()
        .reset_index()
        .rename(columns={kpi_col: "kpi"})
    )

    wide_df = kpi_weekly.copy()
    wide_df["time"] = wide_df["week_start"]
    wide_df["geo"] = "national"

    # Pivot spend/impressions into wide format, one pair of columns per channel.
    for channel in MODEL_CHANNELS:
        ch_data = weekly_df[weekly_df["channel"] == channel]
        ch_agg = (
            ch_data.groupby("week_start")
            .agg(spend=("spend", "sum"), impressions=("impressions", "sum"))
            .reset_index()
            .rename(columns={"spend": f"{channel}_spend", "impressions": f"{channel}_impressions"})
        )
        wide_df = wide_df.merge(ch_agg, on="week_start", how="left")
        wide_df[f"{channel}_spend"] = wide_df[f"{channel}_spend"].fillna(0)
        wide_df[f"{channel}_impressions"] = wide_df[f"{channel}_impressions"].fillna(0)

    # Optional brand-demand control variable.
    has_control = "brand_search" in weekly_df.columns and weekly_df["brand_search"].sum() > 0
    if has_control:
        control_agg = weekly_df.groupby("week_start")["brand_search"].mean().reset_index()
        wide_df = wide_df.merge(control_agg, on="week_start", how="left")
        wide_df["brand_search"] = wide_df["brand_search"].fillna(0)

    if kpi_config.is_revenue:
        wide_df["revenue_per_kpi"] = 1.0

    # Drop channels with zero total spend - Meridian errors on all-zero media
    # columns, and these channels have no signal to fit. They are added back as
    # genuine zero rows (by name) during result extraction.
    active_channels = [ch for ch in MODEL_CHANNELS if wide_df[f"{ch}_spend"].sum() > 0]
    dropped = [ch for ch in MODEL_CHANNELS if ch not in active_channels]
    if dropped:
        logger.warning("Dropping zero-spend channels before fitting: %s", dropped)
    if not active_channels:
        raise ValueError("No channels have non-zero spend")

    # Use spend as the media exposure metric as well: many channels do not report
    # impressions, which would otherwise break Meridian's transformer on all-zero
    # columns. Spend-as-exposure is standard practice for MMM.
    media_spend_cols = [f"{ch}_spend" for ch in active_channels]
    media_cols = [f"{ch}_spend" for ch in active_channels]

    logger.info(
        "Wide frame: %d weeks x %d active channels%s",
        len(weeks), len(active_channels), " + control" if has_control else "",
    )

    kpi_type_str = "revenue" if kpi_config.is_revenue else "non_revenue"
    builder = dfb.DataFrameInputDataBuilder(
        kpi_type=kpi_type_str,
        default_kpi_column="kpi",
        default_time_column="time",
        default_geo_column="geo",
    )
    builder = builder.with_kpi(wide_df)
    if kpi_config.is_revenue:
        builder = builder.with_revenue_per_kpi(wide_df)
    builder = builder.with_media(
        wide_df,
        media_cols=media_cols,
        media_spend_cols=media_spend_cols,
        media_channels=active_channels,
    )
    if has_control:
        builder = builder.with_controls(wide_df, control_cols=["brand_search"])

    input_data = builder.build()
    return input_data, weeks


def prepare_data(
    kpi_type: str,
    params: ModelHyperparameters,
    csv_path: str = DATA_CSV_PATH,
    min_weeks: int = 52,
) -> Tuple:
    """End-to-end data preparation: CSV -> weekly -> validated -> InputData.

    Returns ``(input_data, weekly_df, weeks)``.
    """
    logger.info("=" * 60)
    logger.info("DATA PREPARATION - KPI: %s", kpi_type)
    logger.info("=" * 60)

    raw_df = load_media_csv(csv_path)
    mapped_df = map_channels(raw_df)
    weekly_df = aggregate_to_weekly(mapped_df)
    validate_data(weekly_df, kpi_type, min_weeks=min_weeks)
    input_data, weeks = build_input_data(weekly_df, kpi_type, params)
    logger.info("Data preparation complete.")
    return input_data, weekly_df, weeks
