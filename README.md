# Indian Debt Market News Dashboard

Automated daily pipeline that finds the two most relevant Indian debt
market news stories and writes them into a Notion database, one row
per day.

## What changed from the old version

| Before | Now |
|---|---|
| GNews API (paid tier limits, key required) | Free RSS feeds only — no API key |
| Fetched exactly 2 articles, no filtering | Fetches up to ~150 articles, filters + scores, keeps the best |
| Query: `"India debt market"` | 17 targeted queries across RBI, G-Secs, bond yields, T-Bills, SDL, debt MFs, monetary policy, ECBs, FPI debt, etc. |
| No duplicate protection | Checks new headlines against 60 days of Notion history + auto-archives existing duplicate rows |
| One 70-line script | `config.py` / `utils.py` / `news.py` / `backfill.py`, typed, logged, retried |

The Notion schema is untouched: **News 1 Headline / Date / Link 1 /
News 2 Headline / Link 2**, one row per day.

## Project layout

```
config.py       # every tunable: feeds, keywords, thresholds, retries
utils.py        # RSS fetching, scoring, dedup, Notion API client
news.py         # daily entrypoint (what GitHub Actions runs)
backfill.py     # separate, manual historical import from a CSV
requirements.txt
.github/workflows/news.yml
```

## How the daily pipeline decides what to insert

1. **Housekeeping** — query the last 60 days of Notion rows; if any two
   rows have the same headline(s), archive all but the oldest.
2. **Fetch** — pull every RSS feed in `config.RSS_FEEDS` (Google News
   searches scoped to debt-market keywords and to Reuters/RBI/Business
   Standard/Economic Times/Mint/Moneycontrol/CNBC-TV18, plus RBI's own
   press-release feed and a couple of direct publisher feeds).
3. **Exclude** — drop anything matching an `EXCLUDE_KEYWORDS` hit (IPOs,
   quarterly earnings, "buy/sell rating", Nifty/Sensex stock moves,
   etc.) — this is a hard cut, not a penalty.
4. **Score** — remaining articles get `source trust weight + keyword
   relevance`. Anything below `MIN_SCORE_THRESHOLD` (default 8) is
   dropped.
5. **Dedup within today's batch** — if Reuters and ET both covered the
   same RBI auction, that's one story, not two; fuzzy title matching
   (`DEDUP_SIMILARITY_THRESHOLD`, default 0.82) collapses these to the
   highest-scoring version.
6. **Dedup against history** — anything fuzzy-matching a headline
   already in the last 60 days of Notion rows is dropped, so the same
   story never gets inserted twice across different days.
7. **Insert** — top 2 survivors become today's row. If only 1 survives,
   it's inserted alone and **News 2 is left blank** (not repeated from
   yesterday). If 0 survive, the run logs a warning and exits cleanly
   — no row is written, and this is not treated as a failure.

Everything in steps 3–6 is tunable in `config.py` without touching any
other file.

## Setup

1. Secrets are unchanged — `NOTION_TOKEN` and `DATABASE_ID` must already
   exist as GitHub Actions secrets. **`GNEWS_API_KEY` is no longer
   used** and can be removed from the repo's secrets whenever you like
   (the workflow no longer references it).
2. `pip install -r requirements.txt` locally if you want to test before
   pushing.
3. Push these files. The existing cron schedule (`30 1 * * *`, i.e.
   ~7:00 AM IST) and `workflow_dispatch` trigger are unchanged.

## Testing locally

```bash
export NOTION_TOKEN=secret_xxx
export DATABASE_ID=xxxxxxxx
python news.py
```

Turn on verbose logs with `export LOG_LEVEL=DEBUG`.

## Historical backfill — read this before using `backfill.py`

There is **no free source** (not GNews, not RSS, not RBI's feed) that
can hand you "Indian debt market headlines from a specific past date
on demand." RSS feeds only ever expose recent items. So `backfill.py`
does not attempt to scrape the past automatically — it reads a CSV you
prepare (you can research past headlines manually, or ask an LLM to
help compile a list of real, verifiable headlines with real links) and
inserts one row per date, running the same duplicate checks as the
daily job.

CSV format:

```csv
date,headline1,link1,headline2,link2
2026-06-04,RBI holds repo rate at 6.5% for fourth straight meeting,https://example.com/a,Government raises Rs 30000cr via SDL auction,https://example.com/b
2026-06-05,10-year G-Sec yield eases to 6.9% on softer inflation print,https://example.com/c,,
```

Run it with:

```bash
python backfill.py historical_news.csv --dry-run   # preview only, no writes
python backfill.py historical_news.csv              # actually insert
```

`backfill.py` is never run by GitHub Actions — it's a manual, one-off
tool, kept deliberately separate from `news.py` so a bad backfill run
can never affect the daily automation.

## Tuning knobs (all in `config.py`)

- `NEWS_PER_DAY`, `MAX_ARTICLES` — volume controls
- `RSS_FEEDS` — add/remove sources, adjust trust weights
- `INCLUDE_KEYWORDS` / `EXCLUDE_KEYWORDS` — relevance scoring
- `MIN_SCORE_THRESHOLD` — how relevant a story must be to qualify
- `DEDUP_SIMILARITY_THRESHOLD`, `LOOKBACK_DAYS_FOR_DEDUP` — dedup strictness
- `REMOVE_DUPLICATES` — toggle auto-archiving of duplicate Notion rows
- `MAX_RETRIES`, `RETRY_BACKOFF_SECONDS`, `REQUEST_TIMEOUT_SECONDS` — reliability
