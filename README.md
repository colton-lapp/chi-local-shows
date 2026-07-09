# Chi Local Shows

Automated Chicago local show discovery. Scrapes venue event pages with LLM extraction, finds bands on Spotify via contextual Google/Bing/DuckDuckGo search, and stores everything in a local SQLite database.

## Setup

Install [uv](https://docs.astral.sh/uv/) and [Task](https://taskfile.dev/), then:

```sh
cp .env.example .env    # fill in your API keys
task install            # uv sync + playwright install chromium
```

### Adding dependencies

```sh
uv add <package>          # add to project deps
uv add --group dev <pkg>  # add as dev-only dep (tests, linters)
```

`pyproject.toml` intentionally has no version pins — `uv.lock` handles reproducibility. `uv add` updates both files atomically.

### API Keys

| Key | Where to get it |
|---|---|
| `OPENAI_API_KEY` | platform.openai.com |
| `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET` | developer.spotify.com → create an app |
| `SERPER_API_KEY` (optional) | see below — 2,500 free queries, then ~$1/1,000; band lookup falls back to Bing/DuckDuckGo automatically if unset |

#### Setting up Serper (optional, for the Google-results band-link search tier)

> Google's own Custom Search JSON API is closed to new signups and shuts down entirely on Jan 1, 2027, so this pipeline uses [Serper](https://serper.dev) instead — it returns the same Google search results as JSON, with a much simpler setup (one API key, no Cloud project/billing/search-engine dance).

1. **Sign up**: [serper.dev/signup](https://serper.dev/signup) (no credit card required).
2. **Copy your API key** from the dashboard — this is `SERPER_API_KEY`.
3. **Add it to `.env`** locally:
   ```
   SERPER_API_KEY=...
   ```
4. **Add it as a GitHub Actions secret** so the scheduled `fetch-and-publish.yml` workflow can use it: on GitHub, go to the repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** → add `SERPER_API_KEY`. (`OPENAI_API_KEY`, `SPOTIPY_CLIENT_ID`, and `SPOTIPY_CLIENT_SECRET` need to be set the same way if they aren't already.)

2,500 free queries on signup, then paid tiers starting at ~$1/1,000 queries (band lookup uses 1–2 queries per band). If unset, the pipeline automatically falls back to Bing/DuckDuckGo with no other changes needed — nothing breaks if you skip this.

**Troubleshooting:**
- Check the run logs: `fetch.py` now logs whether Serper is configured at the start of the lookup phase, and prints a summary at the end (queries/errors/hits per tier, Bandcamp URLs found vs. album IDs scraped). If Serper shows `0 errors, 0 band(s) hit` after several queries, that's a strong signal of a key/quota problem rather than a code bug.
- A 403/401 almost always means the key was mistyped, revoked, or the free query balance ran out — check [serper.dev/dashboard](https://serper.dev/dashboard).

## Usage

```sh
task fetch                                      # next 7 days, all venues
task fetch -- --venue "Empty Bottle"            # single venue (good for testing)
task fetch -- --days 14                         # extend window
task fetch -- --skip-lookup                     # scrape only, no band lookup
task fetch -- --retry-errors                    # re-attempt failed band lookups
task fetch -- --venue "Empty Bottle" --skip-lookup  # debug scraping for one venue

task test                                       # run test suite
task db-shows                                   # print shows in DB
task db-bands                                   # print bands + lookup status
task db-reset                                   # delete DB (fresh start)
```

## How It Works

### Phase 1 — Venue scraping

For each active venue in `venues.json`:
1. Fetch the events page (requests → Playwright headless fallback for JS-rendered pages)
2. Pass cleaned page text to GPT-4o-mini with today's date and venue-specific `scrape_notes`
3. LLM returns `{shows: [{bands, date, time, event_url, ticket_url}]}` as JSON
4. Filter dates in Python, deduplicate, insert into `shows.db`

### Phase 2 — Band lookup

For each new band, each step only filling in whatever the previous steps didn't find:
1. **Serper** (Google search results as JSON): `"band name" chicago band` (skipped automatically if `SERPER_API_KEY` isn't set)
2. **Bing via Playwright**: headless browser search
3. **DuckDuckGo**: last web-search fallback (the `ddgs` library is the most prone to rate-limiting under repeated automated queries)
4. **Spotify API direct search**: broadest fallback, if still no Spotify URL
5. Once a Spotify URL is found: pull genres, followers, popularity, image via Spotify API
6. Google search URLs are always generated regardless of outcome (manual fallback for humans)

## Adding Venues

Edit `venues.json`. Minimum required fields:

```json
{
  "name": "My Venue",
  "event_urls": ["https://myvenue.com/events"],
  "active": true
}
```

Optional but useful:
- `scrape_notes`: natural-language hints injected into the LLM prompt (e.g. "Exclude DJ sets, each show lists bands under the date header"). This is the main tuning knob — no code changes needed.
- `address`, `description`: stored in DB, shown in future UI

## Adding Venue-Specific Scrapers

When the generic LLM scraper isn't reliable for a venue (JS-heavy page, unusual format):

1. Create `venue_scrapers/my_venue.py` — implement `scrape(venue_config, days_ahead=7) -> list[ShowResult]`
2. Register it in `venue_scrapers/__init__.py`: add `"My Venue": my_venue.scrape` to `SCRAPER_REGISTRY`

See `venue_scrapers/empty_bottle.py` for a template with comments.

## Acceptance Criteria

Before shipping any change, verify these gates pass in order:

### 1. Unit tests (no API keys needed)
```sh
task test
# Expected: 55 passed
```

What's covered:
- `test_band_lookup.py` — URL building, `_classify_results` bucketing (Spotify/Instagram/Bandcamp/other/search-engine exclusions), Google CSE search (no-op when unconfigured, item parsing), `_merge_found` gap-filling, `lookup_band` flows (Google hit skips Bing/DDG, Bing+DDG merge, DDG hit, all-fail, Instagram-only, Bandcamp-only, no Spotify client)
- `test_db.py` — venue upsert, show insert deduplication, band get-or-create, `update_band_lookup`, `get_bands_needing_lookup` with retry flag, show-band linking, scrape log
- `test_generic_scraper.py` — LLM path, requests fallback to Playwright, empty event_urls early return, fetch error handling, date filtering

### 2. Import sanity (no API keys needed)
```sh
uv run python -c "import db, models, band_lookup, venue_scrapers, browser; print('OK')"
# Expected: OK
```

### 3. CLI help (no API keys needed)
```sh
uv run python fetch.py --help
# Expected: argparse usage block with --venue, --days, --skip-lookup, --retry-errors
```

### 4. Scrape-only smoke test (needs `OPENAI_API_KEY`)
```sh
task fetch -- --venue "Empty Bottle" --skip-lookup
# Expected:
#   - shows.db created
#   - scrape_log has a row with status='ok' and shows_found > 0
#   - shows table has rows; bands table has Google URLs, lookup_status='pending'
#   - Re-running produces no duplicate shows (idempotent)
```

### 5. Full fetch smoke test (needs `OPENAI_API_KEY` + Spotify keys)
```sh
task fetch -- --venue "Empty Bottle"
# Expected:
#   - bands table updated: lookup_status in ('done','not_found','error') for all bands
#   - 'done' bands have at least one of: spotify_url, instagram_url, bandcamp_url
#   - google_general_url populated for every band regardless of outcome
```

---

## Project Structure

```
fetch.py               main runner (2 phases: scrape → lookup)
db.py                  SQLite schema + query helpers
models.py              ShowResult, BandResult dataclasses
band_lookup.py         Google CSE + browser + DDG + Spotify API band lookup
browser.py             Playwright headless browser utilities
venues.json            venue configuration
venue_scrapers/
  __init__.py          scraper registry
  generic.py           LLM-based HTML extraction (default)
  empty_bottle.py      example venue-specific scraper template
tests/                 pytest test suite
```
