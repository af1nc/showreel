"""
Configuration constants for the Bayesian Marketing Mix Model (MMM) runner.

Channel mappings, KPI definitions, model hyperparameters, response-curve grid
and budget-optimisation bounds all live here. The demo reads a local CSV; the
data-source constants at the bottom point at that file.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# =============================================================================
# Data source (demo)
# =============================================================================

# The demo reads a synthetic weekly media CSV. In a production deployment this
# is where you would instead point at your data warehouse; the rest of the
# pipeline is unchanged.
DATA_CSV_PATH = os.environ.get(
    "MMM_DATA_CSV",
    os.path.join(os.path.dirname(__file__), "data", "sample_media.csv"),
)
OUTPUT_DIR = os.environ.get(
    "MMM_OUTPUT_DIR",
    os.path.join(os.path.dirname(__file__), "output"),
)


# =============================================================================
# Channel Mapping
# =============================================================================

# Map raw channel labels from the source data to standardised model channels.
# Keys are lowercase raw values; values are the canonical model channel names.
# Metasearch is deliberately its own bucket (very different response curve from
# paid social) rather than being folded into social.
CHANNEL_MAP: Dict[str, str] = {
    # Display
    "display": "display",
    "display banner": "display",
    "banner": "display",
    "content partnership": "display",
    "mobile apps": "display",
    # Video / online video
    "online video/olv": "video_olv",
    "online video": "video_olv",
    "olv": "video_olv",
    "video/olv": "video_olv",
    "video": "video_olv",
    "video_olv": "video_olv",
    "ctv": "video_olv",
    "connected tv": "video_olv",
    "bvod": "video_olv",
    # Paid Social
    "paid social": "paid_social",
    "paid_social": "paid_social",
    "social": "paid_social",
    "social media": "paid_social",
    # Metasearch (its own response profile)
    "meta": "metasearch",
    "metas": "metasearch",
    "metasearch": "metasearch",
    # Paid Search
    "paid search": "paid_search",
    "paid_search": "paid_search",
    "search": "paid_search",
    # Audio
    "audio": "audio",
    "digital audio": "audio",
    "radio": "audio",
    # Linear TV / OOH / Cinema
    "linear tv": "tv",
    "tv": "tv",
    "ooh": "ooh",
    "dooh": "ooh",
    "cinema": "ooh",
    # Email
    "email": "email",
}

# Ordered list of model channels (canonical column ordering). Note there are
# more channels here than any single dataset is guaranteed to contain - channels
# with zero spend are dropped before fitting, which is exactly the case the
# name-not-index mapping in model_runner.py exists to handle correctly.
MODEL_CHANNELS: List[str] = [
    "display",
    "video_olv",
    "paid_social",
    "paid_search",
    "audio",
    "metasearch",
    "email",
    "ooh",
    "tv",
]


# =============================================================================
# KPI Configuration
# =============================================================================

@dataclass(frozen=True)
class KpiConfig:
    """Configuration for a single KPI target variable."""
    name: str          # Human-readable name
    column: str        # Column name in the weekly DataFrame
    is_revenue: bool   # Revenue metric (ROI threshold 1.0) vs a count metric (0.0)
    description: str


# The demo CSV carries a single generic "kpi" column. Both configs below point
# at it; they differ only in whether the KPI is a revenue metric (which changes
# the profitability threshold and whether revenue_per_kpi is set to 1.0).
KPI_CONFIGS: Dict[str, KpiConfig] = {
    "revenue": KpiConfig(
        name="Revenue",
        column="kpi",
        is_revenue=True,
        description="Attributed revenue (generic monetary KPI)",
    ),
    "conversions": KpiConfig(
        name="Conversions",
        column="kpi",
        is_revenue=False,
        description="Attributed conversions (generic count KPI)",
    ),
}

DEFAULT_KPI = "revenue"
ALL_KPIS: List[str] = ["revenue"]


# =============================================================================
# Model Hyperparameters
# =============================================================================

@dataclass(frozen=True)
class ModelHyperparameters:
    """MCMC and model-structure hyperparameters."""
    # Adstock / carryover
    max_lag: int = 8                # Maximum weeks of carryover effect

    # MCMC sampling. Production settings; the --demo flag overrides these with
    # much smaller counts so a run finishes quickly.
    n_chains: int = 2
    n_adapt: int = 500
    n_burnin: int = 250
    n_keep: int = 250

    # ROI prior: LogNormal(mu, sigma), applied to all channels by default.
    roi_prior_mu: float = 0.2       # Prior mean of log(ROI)
    roi_prior_sigma: float = 0.9    # Prior std of log(ROI)


MODEL_PARAMS = ModelHyperparameters()

# Fast settings used by `main.py --demo` so the example fits in a minute or two.
DEMO_PARAMS = ModelHyperparameters(
    max_lag=4,
    n_chains=2,
    n_adapt=100,
    n_burnin=50,
    n_keep=100,
)


# =============================================================================
# Response Curve Configuration
# =============================================================================

# Spend multipliers for response-curve evaluation. 1.0 = current spend level;
# values below show the curve under-spend, values above show saturation.
RESPONSE_CURVE_MULTIPLIERS: List[float] = [
    0.0, 0.1, 0.2, 0.3, 0.5, 0.75,
    1.0,
    1.25, 1.5, 2.0, 3.0, 5.0,
]


# =============================================================================
# Budget Optimization Configuration
# =============================================================================

# Per-channel spend bounds as a fraction of current spend.
BUDGET_OPT_LOWER_BOUND: float = 0.7    # -30% minimum
BUDGET_OPT_UPPER_BOUND: float = 1.3    # +30% maximum


# =============================================================================
# Seasonality Windows
# =============================================================================

# Named date windows for a --window flag. None means the full date range.
SEASONALITY_WINDOWS: Dict[str, Optional[Tuple[str, str]]] = {
    "full": None,
    "peak_season": ("2025-03-01", "2025-03-31"),
    "h1": ("2025-01-01", "2025-06-30"),
    "h2": ("2025-07-01", "2025-12-31"),
}
