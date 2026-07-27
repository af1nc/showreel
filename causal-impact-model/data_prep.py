"""
Data preparation for the Causal Impact portfolio module.

In the original production system this module read weekly, market-level media
and KPI data from a data warehouse. For this showcase the warehouse read is
stubbed to a local CSV loader. The interesting logic is preserved:

  * automated intervention discovery via rolling spend-drop ("media silence")
    detection, and
  * construction of the pre / post analysis window (AnalysisSpec) that the
    model runner consumes.

Expected CSV shape (weekly rows, one series):
    date,spend,kpi
    2023-01-02,101240.5,8123.4
    ...
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd

from config import (
    DEFAULT_KPI,
    InterventionDetectionParams,
    KPI_CONFIGS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Analysis Spec
# =============================================================================

@dataclass
class AnalysisSpec:
    """Specification for a single Causal Impact analysis run."""
    analysis_type: str          # "media_silence" or "custom"
    label: str                  # Human-readable label
    intervention_date: date     # First day of the post-period
    pre_period_start: date      # Start of the pre-period
    pre_period_end: date        # End of the pre-period (day before intervention)
    post_period_start: date     # Start of the post-period (= intervention_date)
    post_period_end: date       # End of the post-period
    kpi_type: str               # Key into KPI_CONFIGS


# =============================================================================
# CSV Loading (warehouse read stubbed to local file)
# =============================================================================

def load_series_csv(path: str) -> pd.DataFrame:
    """
    Load a weekly series CSV. Returns a DataFrame with a python-date "date"
    column plus a numeric "spend" column and any KPI columns present.
    """
    logger.info("Loading series from %s", path)
    df = pd.read_csv(path)

    if "date" not in df.columns:
        raise ValueError("Input CSV must contain a 'date' column.")
    if "spend" not in df.columns:
        raise ValueError("Input CSV must contain a 'spend' column.")

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0.0)
    df = df.sort_values("date").reset_index(drop=True)

    logger.info(
        "Loaded %d weekly rows, %s to %s, total spend %.0f",
        len(df), df["date"].min(), df["date"].max(), df["spend"].sum(),
    )
    return df


def select_kpi_series(df: pd.DataFrame, kpi_type: str) -> pd.DataFrame:
    """
    Project the loaded frame down to the columns the model needs for one KPI:
    date, y (the KPI outcome), and spend (kept as an optional covariate).
    """
    if kpi_type not in KPI_CONFIGS:
        raise ValueError(f"Unknown KPI type '{kpi_type}'. Known: {list(KPI_CONFIGS)}")

    kpi_col = KPI_CONFIGS[kpi_type].column
    if kpi_col not in df.columns:
        raise ValueError(
            f"KPI '{kpi_type}' expects column '{kpi_col}' which is not in the CSV."
        )

    out = df[["date", "spend"]].copy()
    out["y"] = pd.to_numeric(df[kpi_col], errors="coerce").fillna(0.0)
    return out[["date", "y", "spend"]]


# =============================================================================
# Automated Intervention Discovery (rolling spend-drop / media silence)
# =============================================================================

def detect_interventions(
    series_df: pd.DataFrame,
    params: InterventionDetectionParams,
) -> List[dict]:
    """
    Auto-detect periods where weekly spend drops below a fraction of its
    trailing rolling average for several consecutive weeks (a "media silence").

    Returns a list of event dicts with keys:
        intervention_date, silence_start, silence_end, n_silence_weeks,
        pre_spend_avg, post_spend_avg, drop_pct
    ordered so the most pronounced event (largest sustained drop) comes first.
    """
    logger.info(
        "Detecting spend-drop events (threshold=%.0f%%, window=%d weeks, min_duration=%d weeks)",
        params.spend_drop_threshold * 100,
        params.rolling_window_weeks,
        params.min_silence_weeks,
    )

    df = series_df.sort_values("date").reset_index(drop=True)
    if len(df) < params.rolling_window_weeks + params.min_silence_weeks:
        logger.warning("Not enough rows to run detection.")
        return []

    # Trailing rolling average of spend, shifted so a week compares to the
    # weeks BEFORE it rather than including itself.
    df["rolling_avg"] = (
        df["spend"]
        .rolling(window=params.rolling_window_weeks, min_periods=params.rolling_window_weeks)
        .mean()
        .shift(1)
    )

    # Mark weeks where spend fell below the threshold fraction of trailing avg.
    df["is_silent"] = (
        df["rolling_avg"].notna()
        & (df["rolling_avg"] > 0)
        & (df["spend"] < df["rolling_avg"] * params.spend_drop_threshold)
    )

    # Group consecutive runs of silence.
    df["silence_group"] = (df["is_silent"] != df["is_silent"].shift(1)).cumsum()

    silence_runs = (
        df[df["is_silent"]]
        .groupby("silence_group")
        .agg(
            start=("date", "min"),
            end=("date", "max"),
            n_weeks=("date", "count"),
            avg_spend=("spend", "mean"),
        )
    )

    events: List[dict] = []
    for _, run in silence_runs.iterrows():
        if run["n_weeks"] < params.min_silence_weeks:
            continue

        silence_start = run["start"]
        silence_end = run["end"]

        # Average spend in the window immediately before the silence.
        pre_mask = (
            (df["date"] < silence_start)
            & (df["date"] >= silence_start - timedelta(weeks=params.rolling_window_weeks))
        )
        pre_spend_avg = float(df.loc[pre_mask, "spend"].mean()) if pre_mask.any() else 0.0

        drop_pct = (
            (1.0 - run["avg_spend"] / pre_spend_avg) * 100
            if pre_spend_avg > 0 else 0.0
        )

        events.append({
            "intervention_date": silence_start,
            "silence_start": silence_start,
            "silence_end": silence_end,
            "n_silence_weeks": int(run["n_weeks"]),
            "pre_spend_avg": pre_spend_avg,
            "post_spend_avg": float(run["avg_spend"]),
            "drop_pct": drop_pct,
        })

        logger.info(
            "  Detected silence from %s to %s (%d weeks), spend dropped %.0f%% (%.0f/wk -> %.0f/wk)",
            silence_start, silence_end, int(run["n_weeks"]), drop_pct,
            pre_spend_avg, float(run["avg_spend"]),
        )

    # Most pronounced event first: rank by weeks of silence times drop size.
    events.sort(key=lambda e: e["n_silence_weeks"] * e["drop_pct"], reverse=True)

    logger.info("Detected %d spend-drop event(s).", len(events))
    return events


# =============================================================================
# Spec Construction
# =============================================================================

def build_spec(
    series_df: pd.DataFrame,
    intervention_date: date,
    kpi_type: str,
    params: InterventionDetectionParams,
    analysis_type: str = "media_silence",
    label: Optional[str] = None,
) -> Optional[AnalysisSpec]:
    """
    Build an AnalysisSpec for a single intervention date.

    The pre-period runs from at most min_pre_period_weeks before the
    intervention (floored at the first available week) up to the day before
    the intervention. The post-period runs from the intervention date to the
    end of the available data.
    """
    data_start = series_df["date"].min()
    data_end = series_df["date"].max()

    ideal_pre_start = intervention_date - timedelta(weeks=params.min_pre_period_weeks)
    pre_period_start = max(data_start, ideal_pre_start)

    pre_weeks = (intervention_date - pre_period_start).days // 7
    if pre_weeks < 10:
        logger.warning(
            "Skipping: only %d pre-period weeks before %s (need >= 10 for a stable fit).",
            pre_weeks, intervention_date,
        )
        return None

    pre_period_end = intervention_date - timedelta(days=1)

    if label is None:
        label = f"{analysis_type} @ {intervention_date} ({KPI_CONFIGS[kpi_type].name})"

    return AnalysisSpec(
        analysis_type=analysis_type,
        label=label,
        intervention_date=intervention_date,
        pre_period_start=pre_period_start,
        pre_period_end=pre_period_end,
        post_period_start=intervention_date,
        post_period_end=data_end,
        kpi_type=kpi_type,
    )


def prepare_spec(
    series_df: pd.DataFrame,
    params: InterventionDetectionParams,
    kpi_type: str = DEFAULT_KPI,
    intervention_date: Optional[date] = None,
) -> Optional[AnalysisSpec]:
    """
    Produce an AnalysisSpec.

    If intervention_date is given, use it directly (analysis_type="custom").
    Otherwise run automated discovery and use the most pronounced spend-drop
    event as the intervention (analysis_type="media_silence"). Returns None if
    no intervention can be determined or the pre-period is too short.
    """
    if intervention_date is not None:
        logger.info("Using supplied intervention date: %s", intervention_date)
        label = f"Custom intervention {intervention_date} ({KPI_CONFIGS[kpi_type].name})"
        return build_spec(
            series_df, intervention_date, kpi_type, params,
            analysis_type="custom", label=label,
        )

    events = detect_interventions(series_df, params)
    if not events:
        logger.warning("No intervention auto-detected. Pass an intervention date to analyse.")
        return None

    event = events[0]
    intervention = event["intervention_date"]
    label = (
        f"Auto-detected media silence from {event['silence_start']} "
        f"(spend down {event['drop_pct']:.0f}%) ({KPI_CONFIGS[kpi_type].name})"
    )
    return build_spec(
        series_df, intervention, kpi_type, params,
        analysis_type="media_silence", label=label,
    )
