"""
backfill.py
===========
Separate, on-demand script for inserting HISTORICAL rows — completely
independent of the daily automation in news.py.

Why this exists / important limitation
---------------------------------------
Free RSS feeds (Google News, publisher feeds, RBI's own feed) only ever
expose recent items — there is no free API that can hand you "Indian
debt market headlines from 04/06/2026" on demand. GNews's free tier has
the same limitation. So this script does NOT attempt to auto-scrape the
past; instead it takes a CSV you (or an LLM helping you research past
headlines manually) prepare, validates it, checks it against existing
Notion rows for duplicates, and inserts one row per date.

CSV format (UTF-8, header row required)
----------------------------------------
    date,headline1,link1,headline2,link2

    2026-06-04,RBI holds repo rate at 6.5%,https://...,G-Sec yields ease on...,https://...
    2026-06-05,Government raises Rs 30000cr via SDL auction,https://...,,

`headline2`/`link2` may be left blank for a day with only one story.
`date` must be YYYY-MM-DD.

Usage
-----
    python backfill.py path/to/historical_news.csv
    python backfill.py path/to/historical_news.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import config
import utils
from utils import Article


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historical rows into Notion from a CSV.")
    parser.add_argument("csv_path", type=Path, help="Path to the historical news CSV.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the CSV, check for duplicates, but do not write to Notion.",
    )
    return parser.parse_args(argv)


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    required_cols = {"date", "headline1", "link1", "headline2", "link2"}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or not required_cols.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"CSV must have columns: {sorted(required_cols)}. "
                f"Found: {reader.fieldnames}"
            )
        return list(reader)


def validate_row(row: dict[str, str], line_num: int) -> date:
    try:
        return datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Row {line_num}: invalid date '{row['date']}' (expected YYYY-MM-DD)") from exc


def main(argv: Optional[list[str]] = None) -> int:
    log = utils.setup_logging()
    config.validate_config()
    args = parse_args(argv or sys.argv[1:])

    rows = load_rows(args.csv_path)
    log.info("Loaded %d row(s) from %s", len(rows), args.csv_path)

    client = utils.NotionClient()
    existing_pages = client.query_all_pages()
    existing_headlines = client.get_existing_normalized_headlines(existing_pages)
    existing_dates = {
        client._extract_row_date(p) for p in existing_pages  # noqa: SLF001 - internal helper reuse
    }

    inserted, skipped_existing_date, skipped_duplicate_headline = 0, 0, 0

    for line_num, row in enumerate(rows, start=2):  # header is line 1
        row_date = validate_row(row, line_num)
        headline1 = row["headline1"].strip()
        link1 = row["link1"].strip()
        headline2 = row.get("headline2", "").strip()
        link2 = row.get("link2", "").strip()

        if not headline1 or not link1:
            log.warning("Row %d (%s): missing headline1/link1, skipping.", line_num, row_date)
            continue

        if row_date.isoformat() in existing_dates:
            log.info("Row %d (%s): a row for this date already exists, skipping.", line_num, row_date)
            skipped_existing_date += 1
            continue

        if client.is_duplicate_of_history(headline1, existing_headlines) or (
            headline2 and client.is_duplicate_of_history(headline2, existing_headlines)
        ):
            log.info("Row %d (%s): headline matches existing history, skipping.", line_num, row_date)
            skipped_duplicate_headline += 1
            continue

        first = Article(title=headline1, url=link1, source="backfill-csv")
        second = Article(title=headline2, url=link2, source="backfill-csv") if headline2 else None

        payload = client.build_daily_payload(first, second, on_date=row_date)

        if args.dry_run:
            log.info("[DRY RUN] Would insert row for %s: %s", row_date, headline1)
        else:
            client.insert_page(payload)
            log.info("Inserted historical row for %s", row_date)

        inserted += 1
        # Keep local history sets current so later rows in the same CSV
        # are checked against earlier ones in this same run.
        existing_dates.add(row_date.isoformat())
        existing_headlines.add(utils.normalize_headline(headline1))
        if headline2:
            existing_headlines.add(utils.normalize_headline(headline2))

    log.info(
        "Backfill complete. Inserted: %d, skipped (date exists): %d, skipped (duplicate headline): %d",
        inserted, skipped_existing_date, skipped_duplicate_headline,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
