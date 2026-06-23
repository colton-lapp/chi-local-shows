#!/usr/bin/env python3
"""
Main data-fetch runner. Populates shows.db with shows and band data.

Usage:
  python fetch.py                         # fetch next 7 days for all venues
  python fetch.py --days 14              # extend window
  python fetch.py --venue "Empty Bottle" # single venue (useful for debugging)
  python fetch.py --skip-lookup          # scrape venues only, skip band lookup
  python fetch.py --retry-errors         # re-attempt bands with lookup errors
"""
import argparse
import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

import db
import band_lookup
import venue_scrapers

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

VENUES_JSON = Path(__file__).parent / "venues.json"

# Delay between OpenAI calls (venue scraping)
OPENAI_SLEEP = 1.0
# Delay between band lookups (DuckDuckGo + Spotify)
LOOKUP_SLEEP = 2.0


def _init_spotify():
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials())
        # Quick test to verify credentials work
        sp.search(q="test", type="artist", limit=1)
        return sp
    except Exception as e:
        log.warning(f"Spotify client init failed: {e}")
        log.warning("Band lookup will skip Spotify data (Google fallback URLs still generated)")
        return None


def run(
    days_ahead: int = 7,
    venue_filter: str | None = None,
    skip_lookup: bool = False,
    retry_errors: bool = False,
):
    db.init_db()

    venues = json.loads(VENUES_JSON.read_text())
    active = [v for v in venues if v.get("active", True)]
    if venue_filter:
        active = [v for v in active if v["name"].lower() == venue_filter.lower()]
        if not active:
            log.error(f"No active venue found matching '{venue_filter}'")
            log.info(f"Available venues: {[v['name'] for v in venues if v.get('active', True)]}")
            return

    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    log.info(f"Fetching shows from {today} to {end_date} for {len(active)} venue(s)")

    # ── Phase 1: Venue scraping ──────────────────────────────────────────────
    for venue_cfg in active:
        venue_id = db.upsert_venue(
            name=venue_cfg["name"],
            address=venue_cfg.get("address"),
            description=venue_cfg.get("description"),
        )
        log.info(f"Scraping: {venue_cfg['name']}")

        scraper = venue_scrapers.get_scraper(venue_cfg["name"])
        scrape_error = None

        try:
            shows = scraper(venue_cfg, days_ahead=days_ahead)
        except Exception as e:
            log.error(f"  Scraper raised exception: {e}")
            db.log_scrape(venue_id, status="error", shows_found=0, error_msg=str(e))
            continue

        # Separate error sentinels from real shows
        error_shows = [s for s in shows if s.scrape_error]
        real_shows = [s for s in shows if not s.scrape_error]

        if error_shows:
            errors = "; ".join(s.scrape_error for s in error_shows)
            log.warning(f"  Scrape errors: {errors}")
            scrape_error = errors

        inserted = 0
        for show in real_shows:
            # Double-check date range
            if not (str(today) <= show.date <= str(end_date)):
                continue

            show_id = db.insert_show(
                venue_id=venue_id,
                show_date=show.date,
                show_time=show.time,
                raw_title=show.raw_title,
                event_url=show.event_url,
                ticket_url=show.ticket_url,
            )
            if show_id is None:
                continue  # duplicate, skip

            for position, band_name in enumerate(show.bands):
                band_name = band_name.strip()
                if not band_name:
                    continue
                band_id, _ = db.get_or_create_band(band_name)
                db.link_show_band(show_id, band_id, position)

            inserted += 1

        status = "success" if not scrape_error else ("partial" if inserted > 0 else "error")
        db.log_scrape(venue_id, status=status, shows_found=inserted, error_msg=scrape_error)
        log.info(f"  {inserted} shows saved")
        time.sleep(OPENAI_SLEEP)

    if skip_lookup:
        log.info("Skipping band lookup (--skip-lookup)")
        return

    # ── Phase 2: Band lookup ─────────────────────────────────────────────────
    sp = _init_spotify()
    pending = db.get_bands_needing_lookup(retry_errors=retry_errors)

    if not pending:
        log.info("No bands need lookup")
        return

    log.info(f"Looking up {len(pending)} band(s)")
    for band_row in pending:
        name = band_row["name"]
        log.info(f"  Looking up: {name}")
        try:
            result = band_lookup.lookup_band(name, sp)
            db.update_band_lookup(band_row["id"], result)
            status_note = f"[{result.lookup_status}]"
            if result.spotify_url:
                status_note += f" {result.spotify_url}"
            log.info(f"    {status_note}")
        except Exception as e:
            log.error(f"  Lookup failed for '{name}': {e}")
            fallback = band_lookup.BandResult(
                name=name,
                lookup_status="error",
                lookup_error=str(e),
                **band_lookup.build_google_urls(name),
            )
            db.update_band_lookup(band_row["id"], fallback)
        time.sleep(LOOKUP_SLEEP)

    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Chicago show data into shows.db")
    parser.add_argument("--days", type=int, default=7, metavar="N", help="Days ahead to fetch (default: 7)")
    parser.add_argument("--venue", type=str, metavar="NAME", help="Only scrape this venue by name")
    parser.add_argument("--skip-lookup", action="store_true", help="Skip band lookup phase")
    parser.add_argument("--retry-errors", action="store_true", help="Re-attempt bands with lookup_status=error")
    args = parser.parse_args()

    run(
        days_ahead=args.days,
        venue_filter=args.venue,
        skip_lookup=args.skip_lookup,
        retry_errors=args.retry_errors,
    )
