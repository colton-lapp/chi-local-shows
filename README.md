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
| `GOOGLE_SEARCH_API_KEY` / `GOOGLE_SEARCH_CX` (optional) | see below — free tier is 100 queries/day; band lookup falls back to Bing/DuckDuckGo automatically if unset |

#### Setting up Google Custom Search (optional, for the Google band-link search tier)

This is the only key that isn't a single-click signup, so here's the full path:

1. **Create/select a Google Cloud project**: console.cloud.google.com → project picker (top left) → "New Project" (or reuse an existing one).
2. **Enable the Custom Search API**: in that project, go to [console.cloud.google.com/apis/library/customsearch.googleapis.com](https://console.cloud.google.com/apis/library/customsearch.googleapis.com) and click **Enable**.
3. **Create an API key**: console.cloud.google.com → APIs & Services → Credentials → **Create Credentials** → **API key**. Copy it — this is `GOOGLE_SEARCH_API_KEY`. (Optional: click "Restrict key" and limit it to the Custom Search API so it can't be used for anything else.)
4. **Create a Programmable Search Engine**: go to [programmablesearchengine.google.com](https://programmablesearchengine.google.com/) → **Add** → give it any name → under "What to search," choose **"Search the entire web"** (not a specific site) → **Create**.
5. **Get the Search engine ID**: on the new search engine's overview/setup page, copy the "Search engine ID" — this is `GOOGLE_SEARCH_CX`.
6. **Add both to `.env`** locally:
   ```
   GOOGLE_SEARCH_API_KEY=...
   GOOGLE_SEARCH_CX=...
   ```
7. **Add both as GitHub Actions secrets** so the scheduled `fetch-and-publish.yml` workflow can use them: on GitHub, go to the repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** → add `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_CX`. (`OPENAI_API_KEY`, `SPOTIPY_CLIENT_ID`, and `SPOTIPY_CLIENT_SECRET` need to be set the same way if they aren't already.)

Free tier is 100 queries/day (band lookup uses 1–2 queries per band). If unset, the pipeline automatically falls back to Bing/DuckDuckGo with no other changes needed — nothing breaks if you skip this.

**Troubleshooting:**
- **"Search the entire web" isn't offered when creating the engine** — Google's setup flow sometimes forces you to enter specific sites first. That's fine: since band lookup only ever extracts Spotify/Instagram/Bandcamp links anyway, restrict the engine to `open.spotify.com`, `instagram.com`, and `bandcamp.com` and it'll work the same for this use case (you'll just get `[]` for `other_urls` from the Google tier — Bing/DDG still populate those). If you do want "search entire web," it's usually a toggle on the engine's **Setup → Basics** page after creation, not just at creation time.
- **A key copied from the `<script src="https://cse.google.com/cse.js?cx=...">` embed snippet is not the same as `GOOGLE_SEARCH_API_KEY`.** That snippet is the free client-side widget and needs no API key at all. `GOOGLE_SEARCH_API_KEY` must come from Cloud Console → APIs & Services → Credentials, and if it has an "HTTP referrers" application restriction (common for keys meant for browser widgets), server-side calls from `fetch.py`/GitHub Actions will get a 403 with no `Referer` header. Leave the key unrestricted (or restrict it to the Custom Search API only, not by referrer).
- Check the run logs: `fetch.py` now logs whether Google CSE is configured at the start of the lookup phase, and prints a summary at the end (queries/errors/hits per tier, Bandcamp URLs found vs. album IDs scraped). If Google shows `0 errors, 0 band(s) hit` after several queries, that's a strong signal of a CX/key misconfiguration rather than a code bug.

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
1. **Google Custom Search API**: `"band name" chicago band` (skipped automatically if `GOOGLE_SEARCH_API_KEY`/`GOOGLE_SEARCH_CX` aren't set)
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
