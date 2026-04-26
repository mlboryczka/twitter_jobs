"""Industry taxonomy + priority rules.

The classifier returns one of INDUSTRIES for each posting. The feed worker
uses PRIORITY_1 / PRIORITY_2 / AVOID to decide whether to surface it on the
inbox or auto-dismiss it.

Edit these sets to change the user's industry preferences.
"""

from __future__ import annotations

# All possible industry buckets the classifier can return. "other" is the
# catch-all for anything that doesn't fit cleanly.
INDUSTRIES = [
    "fintech",
    "b2b_saas",
    "ai_ml",
    "dev_tools",
    "vertical_tech",
    "consumer",
    "marketplaces",
    "crypto",
    "hardware",
    "agencies",
    "healthcare",
    "education",
    "logistics",
    "media",
    "defense",
    "cybersecurity",
    "climate",
    "other",
]

# Top-priority verticals — surfaced first on the dashboard.
PRIORITY_1 = {"fintech", "ai_ml", "crypto", "marketplaces"}

# Acceptable verticals — surfaced but de-prioritized.
PRIORITY_2 = {"b2b_saas", "dev_tools", "vertical_tech", "consumer", "hardware", "agencies", "other"}

# Auto-dismissed — inserted with status='dismissed' so it never hits the inbox.
AVOID = {"healthcare", "education", "logistics", "media", "defense", "cybersecurity", "climate"}

# Human-readable labels for the UI.
INDUSTRY_LABELS = {
    "fintech": "Fintech",
    "b2b_saas": "B2B SaaS",
    "ai_ml": "AI / ML",
    "dev_tools": "Dev tools",
    "vertical_tech": "Vertical tech",
    "consumer": "Consumer",
    "marketplaces": "Marketplaces",
    "crypto": "Crypto",
    "hardware": "Hardware",
    "agencies": "Agencies",
    "healthcare": "Healthcare",
    "education": "Education",
    "logistics": "Logistics",
    "media": "Media",
    "defense": "Defense",
    "cybersecurity": "Cybersecurity",
    "climate": "Climate",
    "other": "Other",
}


def get_priority(industry: str | None) -> int:
    """Return 1 for PRIORITY_1, 2 for PRIORITY_2, 0 for AVOID, 2 for unknown."""
    if industry in AVOID:
        return 0
    if industry in PRIORITY_1:
        return 1
    return 2


def is_avoided(industry: str | None) -> bool:
    return industry in AVOID
