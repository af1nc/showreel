"""
Configuration for the spend -> brand-demand -> revenue lag model.

This standalone version holds the input CSV path, the output directory,
the channel definitions, and the econometric hyperparameters (max lag,
significance level, IRF horizon, bootstrap settings). There are no
warehouse or cloud references: the module reads a local CSV and writes
local files.
"""

from pathlib import Path
from typing import Dict, List

# =============================================================================
# Paths
# =============================================================================

# Folder that contains this file.
BASE_DIR = Path(__file__).resolve().parent

# Input: a weekly market panel (one row per market per week).
DATA_DIR = BASE_DIR / "data"
SAMPLE_CSV = DATA_DIR / "sample_market_weekly.csv"

# Output: model results (CSV + JSON) are written here.
OUTPUT_DIR = BASE_DIR / "output"


# =============================================================================
# Column definitions
# =============================================================================

# The demand-signal column hypothesised to mediate spend -> revenue.
DEMAND_SIGNAL_COLUMN = "brand_search"

# The revenue column.
REVENUE_COLUMN = "revenue"

# Total spend across all channels.
TOTAL_SPEND_COLUMN = "total_spend"

# Per-channel spend columns. The model fits one extra VAR per channel to see
# which channel drives the demand signal (and revenue) most.
CHANNEL_SPEND_COLUMNS: Dict[str, str] = {
    "search": "search_spend",
    "social": "social_spend",
    "display": "display_spend",
    "video": "video_spend",
}

# Every numeric column the loader z-score standardises before modelling.
NUMERIC_COLUMNS: List[str] = [
    TOTAL_SPEND_COLUMN,
    *CHANNEL_SPEND_COLUMNS.values(),
    DEMAND_SIGNAL_COLUMN,
    REVENUE_COLUMN,
]


# =============================================================================
# Model hyperparameters
# =============================================================================

# Maximum lag (in weeks) to test for Granger causality and VAR order selection.
MAX_LAG_WEEKS = 12

# Minimum weeks of data required per market.
MIN_WEEKS = 52

# Granger causality significance threshold.
SIGNIFICANCE_LEVEL = 0.05

# Number of bootstrap replications for IRF confidence intervals.
IRF_BOOTSTRAP_REPS = 200

# IRF horizon (weeks into the future to compute impulse responses).
IRF_HORIZON = 24

# Bootstrap confidence interval level (0.10 gives a 90% CI).
IRF_CI_ALPHA = 0.10
