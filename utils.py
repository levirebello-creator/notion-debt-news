"""
utils.py
========
All reusable building blocks for the pipeline:

  fetch_all_articles()        -> pull + parse every RSS feed in config.RSS_FEEDS
  filter_and_score(articles)  -> exclude junk, score the rest, sort best-first
  dedupe_batch(articles)      -> collapse near-identical stories fetched today
  NotionClient                -> query existing rows, archive duplicates, insert a page

Nothing here is CLI-specific — news.py and backfill.py both import from
this module so the actual "what do I do today" logic stays short and
readable in the entrypoint scripts.
"""
from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import feedparser
import requests

import config


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("debt_market_news")


log = logging.getLogger("debt_market_news")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Article:
    title: str
    url: str
    source: str
    published: Optional[datetime] = None
    score: int = 0

    @property
    def domain(self) -> str:
        try:
            netloc = urlparse(self.url).netloc.lower()
            return netloc[4:] if netloc.startswith("www.") else netloc
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# HTTP with retries
# ---------------------------------------------------------------------------
def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    json_body: Optional[dict] = None,
    timeout: int = config.REQUEST_TIMEOUT_SECONDS,
) -> requests.Response:
    """Small retry wrapper so a single flaky RSS host or a transient
    Notion 502 doesn't fail the whole run."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = requests.request(
                method, url, headers=headers, json=json_body, timeout=timeout
            )
            if response.status_code >= 500:
                raise requests.HTTPError(
                    f"Server error {response.status_code} from {url}"
                )
            return response
        except (requests.RequestException,) as exc:
            last_exc = exc
            wait = config.RETRY_BACKOFF_SECONDS * attempt
            log.warning(
                "Request failed (attempt %s/%s) for %s: %s. Retrying in %.1fs",
                attempt, config.MAX_RETRIES, url, exc, wait,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# RSS fetching
# ---------------------------------------------------------------------------
def fetch_all_articles() -> list[Article]:
    """Pull every configured RSS feed and return a flat, capped list of
    Article objects. Individual feed failures are logged and skipped
    rather than aborting the whole run."""
    articles: list[Article] = []

    for source_name, feed_url, trust_weight in config.RSS_FEEDS:
        try:
            resp = _request_with_retry(
                "GET", feed_url, headers={"User-Agent": config.USER_AGENT}
            )
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                log.warning("Feed '%s' failed to parse: %s", source_name, parsed.bozo_exception)
                continue

            for entry in parsed.entries:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if not title or not link:
                    continue

                published_dt = None
                if getattr(entry, "published_parsed", None):
                    published_dt = datetime(*entry.published_parsed[:6])

                article = Article(
                    title=title,
                    url=link,
                    source=source_name,
                    published=published_dt,
                    score=trust_weight,  # seed score with source trust weight
                )
                articles.append(article)

        except Exception as exc:  # noqa: BLE001 - a single bad feed must not kill the run
            log.warning("Skipping feed '%s' due to error: %s", source_name, exc)
            continue

    log.info("Fetched %d raw articles across %d feeds", len(articles), len(config.RSS_FEEDS))
    return articles[: config.MAX_ARTICLES * 3]  # generous cap pre-filtering; final cap applied later


# ---------------------------------------------------------------------------
# Scoring & filtering
# ---------------------------------------------------------------------------
def is_excluded(text: str) -> bool:
    lowered = text.lower()
    return any(bad in lowered for bad in config.EXCLUDE_KEYWORDS)


def keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(points for kw, points in config.INCLUDE_KEYWORDS.items() if kw in lowered)


def filter_and_score(articles: list[Article]) -> list[Article]:
    """Exclude irrelevant articles (IPOs, earnings, equities), score the
    rest on keyword relevance + source trust, and return only those
    clearing MIN_SCORE_THRESHOLD, sorted best-first."""
    eligible: list[Article] = []

    for article in articles:
        combined_text = article.title
        if is_excluded(combined_text):
            continue

        # article.score currently holds only the source trust weight
        # (seeded in fetch_all_articles); add keyword relevance now.
        article.score += keyword_score(combined_text)

        if article.score >= config.MIN_SCORE_THRESHOLD:
            eligible.append(article)

    eligible.sort(key=lambda a: a.score, reverse=True)
    log.info("%d of %d articles cleared the relevance filter", len(eligible), len(articles))
    return eligible[: config.MAX_ARTICLES]


# ---------------------------------------------------------------------------
# Fuzzy matching helpers (shared by within-batch and vs-history dedup)
# ---------------------------------------------------------------------------
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_headline(text: str) -> str:
    text = text.lower().strip()
    text = _PUNCT_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text


def _similar(a: str, b: str) -> float:
    """Headline similarity, combining two signals:

    - character-level ratio (difflib) — catches near-identical strings
      and minor rewording of the same phrase order.
    - word-overlap / Jaccard ratio — catches the common case of the same
      story worded differently by two outlets, e.g. "RBI holds repo
      rate steady at 6.5%" vs "RBI keeps repo rate unchanged at 6.5
      percent", where character-level similarity alone is too low.

    We take the max of the two so either signal can trigger a match.
    """
    char_ratio = difflib.SequenceMatcher(None, a, b).ratio()

    words_a, words_b = set(a.split()), set(b.split())
    if not words_a or not words_b:
        jaccard = 0.0
    else:
        jaccard = len(words_a & words_b) / len(words_a | words_b)

    return max(char_ratio, jaccard)


def dedupe_batch(articles: list[Article]) -> list[Article]:
    """Collapse near-duplicate stories that multiple sources reported on
    the same day (e.g. Reuters and ET both covering the same RBI
    auction). Keeps the highest-scoring representative of each cluster."""
    kept: list[Article] = []
    kept_norms: list[str] = []

    for article in articles:  # already sorted best-first by filter_and_score
        norm = normalize_headline(article.title)
        if any(_similar(norm, existing) >= config.DEDUP_SIMILARITY_THRESHOLD for existing in kept_norms):
            continue
        kept.append(article)
        kept_norms.append(norm)

    log.info("%d unique stories remain after within-batch dedup", len(kept))
    return kept


# ---------------------------------------------------------------------------
# Notion client
# ---------------------------------------------------------------------------
class NotionClient:
    def __init__(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {config.NOTION_TOKEN}",
            "Notion-Version": config.NOTION_VERSION,
            "Content-Type": "application/json",
        }

    # -- reading -------------------------------------------------------
    def query_all_pages(self, *, since: Optional[date] = None) -> list[dict[str, Any]]:
        """Return every row in the database (optionally filtered to
        Date >= `since`), handling pagination transparently."""
        pages: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        body_filter = None
        if since is not None:
            body_filter = {
                "property": config.PROP_DATE,
                "date": {"on_or_after": since.isoformat()},
            }

        while True:
            body: dict[str, Any] = {"page_size": 100}
            if body_filter:
                body["filter"] = body_filter
            if cursor:
                body["start_cursor"] = cursor

            resp = _request_with_retry(
                "POST",
                f"{config.NOTION_API_BASE}/databases/{config.DATABASE_ID}/query",
                headers=self.headers,
                json_body=body,
            )
            resp.raise_for_status()
            data = resp.json()
            pages.extend(data.get("results", []))

            if data.get("has_more"):
                cursor = data.get("next_cursor")
            else:
                break

        log.info("Fetched %d existing rows from Notion", len(pages))
        return pages

    @staticmethod
    def _extract_headlines(page: dict[str, Any]) -> list[str]:
        """Pull News 1 Headline (title prop) and News 2 Headline (rich_text
        prop) out of a Notion page object."""
        props = page.get("properties", {})
        headlines: list[str] = []

        title_prop = props.get(config.PROP_NEWS1_TITLE, {}).get("title", [])
        for chunk in title_prop:
            plain = chunk.get("plain_text") or chunk.get("text", {}).get("content", "")
            if plain:
                headlines.append(plain)

        text_prop = props.get(config.PROP_NEWS2_TITLE, {}).get("rich_text", [])
        for chunk in text_prop:
            plain = chunk.get("plain_text") or chunk.get("text", {}).get("content", "")
            if plain:
                headlines.append(plain)

        return headlines

    @staticmethod
    def _extract_row_date(page: dict[str, Any]) -> Optional[str]:
        props = page.get("properties", {})
        date_prop = props.get(config.PROP_DATE, {}).get("date")
        if date_prop:
            return date_prop.get("start")
        return None

    def get_existing_normalized_headlines(self, pages: list[dict[str, Any]]) -> set[str]:
        headlines: set[str] = set()
        for page in pages:
            for h in self._extract_headlines(page):
                headlines.add(normalize_headline(h))
        return headlines

    def is_duplicate_of_history(self, title: str, existing_norm_headlines: set[str]) -> bool:
        norm = normalize_headline(title)
        return any(
            _similar(norm, existing) >= config.DEDUP_SIMILARITY_THRESHOLD
            for existing in existing_norm_headlines
        )

    # -- cleanup ---------------------------------------------------------
    def archive_page(self, page_id: str) -> None:
        resp = _request_with_retry(
            "PATCH",
            f"{config.NOTION_API_BASE}/pages/{page_id}",
            headers=self.headers,
            json_body={"archived": True},
        )
        resp.raise_for_status()

    def remove_duplicate_rows(self, pages: list[dict[str, Any]]) -> int:
        """Group rows by their set of normalized headlines; for any group
        with more than one row, keep only the oldest (by Date, falling
        back to created_time) and archive the rest. Returns count archived."""
        if not config.REMOVE_DUPLICATES:
            return 0

        groups: dict[str, list[dict[str, Any]]] = {}
        for page in pages:
            headlines = self._extract_headlines(page)
            if not headlines:
                continue
            key = "|".join(sorted(normalize_headline(h) for h in headlines))
            groups.setdefault(key, []).append(page)

        archived_count = 0
        for key, group_pages in groups.items():
            if len(group_pages) < 2:
                continue

            def sort_key(p: dict[str, Any]) -> str:
                return self._extract_row_date(p) or p.get("created_time", "")

            group_pages.sort(key=sort_key)  # oldest first
            for stale_page in group_pages[1:]:  # keep [0], archive the rest
                try:
                    self.archive_page(stale_page["id"])
                    archived_count += 1
                    log.info("Archived duplicate row %s", stale_page["id"])
                except Exception as exc:  # noqa: BLE001
                    log.warning("Failed to archive duplicate row %s: %s", stale_page["id"], exc)

        if archived_count:
            log.info("Archived %d duplicate row(s) from Notion", archived_count)
        return archived_count

    # -- writing ---------------------------------------------------------
    def build_daily_payload(
        self, first: Article, second: Optional[Article], *, on_date: Optional[date] = None
    ) -> dict[str, Any]:
        on_date = on_date or date.today()
        properties: dict[str, Any] = {
            config.PROP_NEWS1_TITLE: {
                "title": [{"text": {"content": first.title}}]
            },
            config.PROP_DATE: {"date": {"start": on_date.isoformat()}},
            config.PROP_LINK1: {"url": first.url},
        }
        if second is not None:
            properties[config.PROP_NEWS2_TITLE] = {
                "rich_text": [{"text": {"content": second.title}}]
            }
            properties[config.PROP_LINK2] = {"url": second.url}
        else:
            # Explicitly blank rather than omitted, so a stale value from
            # a previous manual edit can't linger if this row is ever reused.
            properties[config.PROP_NEWS2_TITLE] = {"rich_text": []}
            properties[config.PROP_LINK2] = {"url": None}

        return {"parent": {"database_id": config.DATABASE_ID}, "properties": properties}

    def insert_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = _request_with_retry(
            "POST",
            f"{config.NOTION_API_BASE}/pages",
            headers=self.headers,
            json_body=payload,
        )
        if resp.status_code >= 400:
            log.error("Notion insert failed: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()
