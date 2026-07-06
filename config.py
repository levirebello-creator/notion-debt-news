"""
config.py
=========
Single source of truth for every tunable in the Indian Debt Market News
pipeline. `news.py`, `backfill.py`, and `utils.py` should never hardcode
a keyword, feed URL, or threshold — they import it from here instead.

Nothing in this file makes network calls. It is safe to import from
anywhere, including test scripts.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Notion credentials & schema
# ---------------------------------------------------------------------------
# Read at import time so a missing secret fails fast with a clear error
# instead of a confusing 401 deep inside a request.
NOTION_TOKEN: str = os.environ.get("NOTION_TOKEN", "")
DATABASE_ID: str = os.environ.get("DATABASE_ID", "")

NOTION_VERSION: str = "2022-06-28"
NOTION_API_BASE: str = "https://api.notion.com/v1"

# Exact property names in the "Daily Financial News" database.
# DO NOT CHANGE these unless the Notion database schema itself changes.
PROP_NEWS1_TITLE = "News 1 Headline"   # Title property
PROP_DATE = "Date"                     # Date property
PROP_LINK1 = "Link 1"                  # URL property
PROP_NEWS2_TITLE = "News 2 Headline"   # Text (rich_text) property
PROP_LINK2 = "Link 2"                  # URL property

# ---------------------------------------------------------------------------
# Volume controls
# ---------------------------------------------------------------------------
NEWS_PER_DAY: int = 2     # max articles inserted as one row per day
MAX_ARTICLES: int = 50    # cap on raw articles pulled across all feeds before filtering

# ---------------------------------------------------------------------------
# RSS sources
# ---------------------------------------------------------------------------
# Each tuple: (source_label, rss_url, trust_weight)
# trust_weight is added straight into an article's relevance score, so
# articles from RBI / Reuters / ET etc. are preferred over unknown sites
# when several stories are otherwise tied on keyword relevance.
#
# All of these are free RSS endpoints — no API keys required.
RSS_FEEDS: list[tuple[str, str, int]] = [
    # --- Topic-scoped Google News RSS searches (broad net) ---
    ("Google News: RBI/Monetary Policy",
     "https://news.google.com/rss/search?q=RBI+OR+%22monetary+policy%22+OR+%22repo+rate%22+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     10),
    ("Google News: G-Sec/Treasury",
     "https://news.google.com/rss/search?q=%22government+securities%22+OR+%22G-Sec%22+OR+%22treasury+bill%22+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     10),
    ("Google News: Corporate Bonds/Yields",
     "https://news.google.com/rss/search?q=%22corporate+bond%22+OR+%22bond+yield%22+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     9),
    ("Google News: Debt MF/Sovereign Debt",
     "https://news.google.com/rss/search?q=%22debt+mutual+fund%22+OR+%22sovereign+debt%22+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     8),
    ("Google News: ECB/FPI Debt/SDL",
     "https://news.google.com/rss/search?q=%22external+commercial+borrowing%22+OR+%22FPI+debt%22+OR+SDL+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     8),
    ("Google News: Bond Auctions",
     "https://news.google.com/rss/search?q=%22bond+auction%22+India+RBI+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     10),

    # --- Site-scoped Google News queries for preferred publishers ---
    ("Reuters (site-scoped)",
     "https://news.google.com/rss/search?q=site:reuters.com+(bond+OR+RBI+OR+%22government+securities%22)+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     15),
    ("Economic Times (site-scoped)",
     "https://news.google.com/rss/search?q=site:economictimes.indiatimes.com+(bond+OR+RBI+OR+%22g-sec%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     14),
    ("Business Standard (site-scoped)",
     "https://news.google.com/rss/search?q=site:business-standard.com+(bond+OR+RBI+OR+%22debt+market%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     14),
    ("Mint (site-scoped)",
     "https://news.google.com/rss/search?q=site:livemint.com+(bond+OR+RBI+OR+%22debt+market%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     13),
    ("Moneycontrol (site-scoped)",
     "https://news.google.com/rss/search?q=site:moneycontrol.com+(bond+OR+RBI+OR+%22debt+market%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     12),
    ("CNBC-TV18 (site-scoped)",
     "https://news.google.com/rss/search?q=site:cnbctv18.com+(bond+OR+RBI+OR+%22debt+market%22)+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
     12),

    # --- Direct publisher feeds (official, free, no key needed) ---
    ("RBI Press Releases", "https://www.rbi.org.in/pressreleases_rss.xml", 20),
    ("Business Standard: Finance", "https://www.business-standard.com/rss/finance-103.rss", 11),
    ("Economic Times: Bonds", "https://economictimes.indiatimes.com/markets/bonds/rssfeeds/50290587.cms", 11),
]

# Domains considered "trusted" for reporting / diagnostics purposes.
TRUSTED_DOMAINS: set[str] = {
    "reuters.com",
    "rbi.org.in",
    "business-standard.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "moneycontrol.com",
    "cnbctv18.com",
}

# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------
# Positive signal: term found in title/summary adds this many points.
# Matching is case-insensitive substring matching (see utils.score_article).
INCLUDE_KEYWORDS: dict[str, int] = {
    "rbi": 8,
    "reserve bank of india": 8,
    "government securities": 10,
    "g-sec": 10,
    "gsec": 10,
    "corporate bond": 9,
    "bond yield": 9,
    "yield curve": 8,
    "treasury bill": 9,
    "t-bill": 9,
    "sdl": 7,
    "state development loan": 7,
    "debt mutual fund": 7,
    "monetary policy": 8,
    "repo rate": 8,
    "reverse repo": 6,
    "sovereign debt": 8,
    "bond auction": 10,
    "external commercial borrowing": 8,
    "ecb": 5,
    "fpi debt": 8,
    "foreign portfolio investment": 5,
    "inflation": 4,
    "cpi": 4,
    "wpi": 4,
    "debt market": 10,
    "bond market": 9,
    "10-year bond": 8,
    "10-year yield": 8,
    "gilt": 7,
    "ncd": 6,
    "non-convertible debenture": 6,
    "credit rating": 4,
    "rating downgrade": 5,
    "rating upgrade": 5,
}

# Negative signal: any of these appearing means the article is almost
# certainly about equities / IPOs / earnings rather than debt markets.
# A single hit is enough to hard-exclude the article (see utils.is_excluded).
EXCLUDE_KEYWORDS: list[str] = [
    "ipo",
    "initial public offering",
    "q1 results", "q2 results", "q3 results", "q4 results",
    "quarterly results", "earnings call", "earnings report",
    "stock recommendation", "buy rating", "sell rating", "target price",
    "share price", "stock price", "multibagger",
    "nifty", "sensex", "midcap stock", "smallcap stock",
    "listing gains", "dividend announcement",
]

# Minimum score an article must reach to be eligible for insertion at all.
MIN_SCORE_THRESHOLD: int = 8

# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
REMOVE_DUPLICATES: bool = True            # auto-archive duplicate Notion rows
DEDUP_SIMILARITY_THRESHOLD: float = 0.55  # 0-1 fuzzy match ratio (max of char-ratio, word-overlap)
LOOKBACK_DAYS_FOR_DEDUP: int = 60         # how many days of Notion history to check against

# ---------------------------------------------------------------------------
# Networking / reliability
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS: int = 15
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 2.0
USER_AGENT: str = (
    "IndiaDebtMarketNewsBot/1.0 (+https://github.com/) "
    "Mozilla/5.0 (compatible)"
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


def validate_config() -> None:
    """Fail fast and loud if required secrets are missing.

    Called once at the top of news.py / backfill.py so a missing
    GitHub secret produces a clear error instead of a mysterious
    401 Unauthorized three network calls later.
    """
    missing = [name for name, val in (
        ("NOTION_TOKEN", NOTION_TOKEN),
        ("DATABASE_ID", DATABASE_ID),
    ) if not val]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set them as GitHub Actions secrets or in your local environment."
        )
