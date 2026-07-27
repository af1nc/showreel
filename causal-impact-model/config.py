"""
Configuration for the Causal Impact portfolio module.

KPI definitions, analysis type definitions, intervention detection
thresholds, and default input/output paths all live here so the rest of
the code stays declarative. This module has no warehouse dependencies:
the original production version read from and wrote to a data warehouse,
which has been stubbed to local CSV/JSON files for this showcase.
"""

from dataclasses import dataclass
from typing import Dict, List


# =============================================================================
# Input / Output Paths
# =============================================================================

# Default synthetic series shipped with the demo. Weekly rows with columns:
#   date (ISO week-start), spend, kpi
DEFAULT_INPUT_CSV = "data/sample_series.csv"

# Results are written here as CSV + JSON (no warehouse in this showcase).
DEFAULT_OUTPUT_DIR = "output"

# Credible interval width for the counterfactual. alpha=0.1 gives a 90%
# interval, matching the default used by the production model.
CREDIBLE_INTERVAL_ALPHA = 0.1


# =============================================================================
# KPI Configuration
# =============================================================================

@dataclass(frozen=True)
class KpiConfig:
    """Configuration for a single KPI target variable."""
    name: str          # Human-readable name
    column: str        # Column name in the input series
    description: str   # Description for logging / metadata


# The production system carried a whole framework of KPIs (revenue, bookings,
# sessions, brand search interest, ...). For the showcase we keep the same
# extensible shape but point the default KPI at the generic "kpi" column that
# the sample CSV provides. Add more entries here to measure other columns.
KPI_CONFIGS: Dict[str, KpiConfig] = {
    "conversions": KpiConfig(
        name="Conversions",
        column="kpi",
        description="Primary outcome metric (conversions, bookings, revenue, sessions, ...).",
    ),
}

# The KPI used when none is passed on the command line.
DEFAULT_KPI = "conversions"


# =============================================================================
# Analysis Type Definitions
# =============================================================================

ANALYSIS_TYPES = {
    "media_silence": "Auto-detected period of significant spend reduction",
    "custom": "User-defined intervention date and periods",
}


# =============================================================================
# Intervention Detection Parameters
# =============================================================================

# These thresholds control automated intervention discovery: a "media
# silence" (or spend-drop) event is a stretch of weeks where paid spend
# collapses relative to its recent trailing average. When such an event is
# found it becomes the intervention date; otherwise the caller supplies one.
#
# The defaults are intentionally permissive. In practice, always-on accounts
# rarely drop spend to near zero, so overly strict thresholds detect nothing.
# A drop below half of the trailing average, sustained for a few weeks, is a
# good balance between sensitivity and false positives.
@dataclass(frozen=True)
class InterventionDetectionParams:
    """Parameters for auto-detecting spend-drop (media silence) periods."""

    # A week is "silent" when its spend falls below this fraction of the
    # trailing rolling average. 0.50 means "spend fell below half of trailing".
    spend_drop_threshold: float = 0.50

    # Number of trailing weeks used to compute the rolling average.
    rolling_window_weeks: int = 8

    # Minimum consecutive silent weeks required to qualify as an event.
    min_silence_weeks: int = 3

    # Minimum pre-period length (weeks before the intervention) needed for a
    # robust BSTS fit. About one quarter of weekly data is sufficient.
    min_pre_period_weeks: int = 13


DETECTION_PARAMS = InterventionDetectionParams()
