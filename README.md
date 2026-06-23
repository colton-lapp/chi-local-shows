# Chi Local Shows

Automated Chicago local show discovery. Scrapes venue event pages with LLM extraction, finds bands on Spotify via contextual Google/Bing search, and stores everything in a local SQLite database.

## Setup

Install [uv](https://docs.astral.sh/uv/) and [Task](https://taskfile.dev/), then:

```sh
cp .env.example .env    # fill in your API keys
task install            # uv sync + playwright install chromium
```

### API Keys

| Key | Where to get it |
|---|---|
| `OPENAI_API_KEY` | platform.openai.com |
| `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET` | developer.spotify.com → create an app |

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

For each new band:
1. **DuckDuckGo**: `"band name" site:open.spotify.com/artist chicago`
2. **Bing via Playwright**: headless browser search (fallback when DDG rate-limits)
3. **Spotify API direct search**: broadest fallback
4. Once a Spotify URL is found: pull genres, followers, popularity, image via Spotify API
5. Google search URLs are always generated regardless of outcome (manual fallback)

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

## Project Structure

```
fetch.py               main runner (2 phases: scrape → lookup)
db.py                  SQLite schema + query helpers
models.py              ShowResult, BandResult dataclasses
band_lookup.py         DDG + browser + Spotify API band lookup
browser.py             Playwright headless browser utilities
venues.json            venue configuration
venue_scrapers/
  __init__.py          scraper registry
  generic.py           LLM-based HTML extraction (default)
  empty_bottle.py      example venue-specific scraper template
tests/                 pytest test suite
```
