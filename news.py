"""
news.py
=======
Daily entrypoint. Run by GitHub Actions on the cron schedule (and via
workflow_dispatch for manual runs).

Pipeline:
    1. Validate config / secrets.
    2. Pull existing Notion rows; archive any duplicate rows found (housekeeping).
    3. Build a set of normalized headlines from recent history (for dedup).
    4. Fetch up to ~150 raw articles across all configured RSS feeds.
    5. Drop anything matching an exclude keyword (IPOs, earnings, equities...).
    6. Score the rest on keyword relevance + source trust; keep the top MAX_ARTICLES.
    7. Collapse near-duplicate stories fetched today (same story, multiple outlets).
    8. Drop anything that matches a headline already in Notion history.
    9. Take the top NEWS_PER_DAY (usually 2) and insert exactly one row.
       - If only one qualifies, insert it alone and leave News 2 blank.
       - If zero qualify, log a warning and exit without inserting anything.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import config
import utils


def main() -> int:
    log = utils.setup_logging()
    config.validate_config()

    client = utils.NotionClient()

    # --- 1. Housekeeping: clean up any duplicate rows already in Notion ---
    lookback_start = date.today() - timedelta(days=config.LOOKBACK_DAYS_FOR_DEDUP)
    existing_pages = client.query_all_pages(since=lookback_start)
    client.remove_duplicate_rows(existing_pages)

    # Re-fetch after cleanup so the history set used for dedup below
    # reflects the post-cleanup state (harmless if nothing was archived).
    existing_pages = client.query_all_pages(since=lookback_start)
    existing_headlines = client.get_existing_normalized_headlines(existing_pages)
    log.info("Loaded %d normalized historical headlines for dedup", len(existing_headlines))

    # --- 2. Fetch & filter today's candidate articles ---
    raw_articles = utils.fetch_all_articles()
    scored_articles = utils.filter_and_score(raw_articles)
    unique_today = utils.dedupe_batch(scored_articles)

    fresh_articles = [
        a for a in unique_today
        if not client.is_duplicate_of_history(a.title, existing_headlines)
    ]
    log.info(
        "%d candidate(s) remain after removing stories already in Notion history",
        len(fresh_articles),
    )

    # --- 3. Decide what to insert today ---
    chosen = fresh_articles[: config.NEWS_PER_DAY]

    if not chosen:
        log.warning("No new, relevant, non-duplicate articles found today. Skipping insert.")
        return 0  # not a failure — just a quiet news day

    first = chosen[0]
    second = chosen[1] if len(chosen) > 1 else None

    if second is None:
        log.info("Only one qualifying article today; inserting it alone (News 2 left blank).")

    payload = client.build_daily_payload(first, second)
    result = client.insert_page(payload)

    log.info("Inserted row for %s", date.today().isoformat())
    log.info("News 1: %s (%s)", first.title, first.source)
    if second:
        log.info("News 2: %s (%s)", second.title, second.source)

    print("Successfully added today's news to Notion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
