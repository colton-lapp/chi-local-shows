#!/usr/bin/env python3
"""
Export DB data to JSON cache and restore from JSON cache.

Usage:
    uv run python cache.py export [output_path]  # default: shows_cache.json
    uv run python cache.py import [input_path]   # default: shows_cache.json
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import db
from models import BandResult

CACHE_PATH = Path(__file__).parent / "shows_cache.json"
_EXPORT_DAYS = 30  # wider than the 14-day display window to capture all fetched data


def export_cache(output_path: Path = CACHE_PATH) -> None:
    today = date.today()
    end = today + timedelta(days=_EXPORT_DAYS)

    with db.get_conn() as conn:
        shows = conn.execute(
            """SELECT s.*, v.name AS venue_name, v.address AS venue_address
               FROM shows s JOIN venues v ON s.venue_id = v.id
               WHERE s.show_date BETWEEN ? AND ?
               ORDER BY s.show_date, s.show_time""",
            (today.isoformat(), end.isoformat()),
        ).fetchall()

        show_list = []
        for show in shows:
            show_dict = dict(show)
            bands = conn.execute(
                """SELECT b.*, sb.position
                   FROM bands b JOIN show_bands sb ON b.id = sb.band_id
                   WHERE sb.show_id = ?
                   ORDER BY sb.position""",
                (show["id"],),
            ).fetchall()
            show_dict["bands"] = [dict(b) for b in bands]
            show_list.append(show_dict)

    cache = {
        "exported_at": datetime.now().isoformat(),
        "shows": show_list,
    }
    output_path.write_text(json.dumps(cache, indent=2, default=str), encoding="utf-8")
    print(f"Exported {len(show_list)} shows to {output_path}")


def import_cache(input_path: Path = CACHE_PATH) -> None:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    shows = data["shows"]

    db.init_db()

    for show in shows:
        venue_id = db.upsert_venue(show["venue_name"], show.get("venue_address"))

        show_id = db.insert_show(
            venue_id=venue_id,
            show_date=show["show_date"],
            show_time=show.get("show_time"),
            raw_title=show.get("raw_title"),
            event_url=show.get("event_url"),
            ticket_url=show.get("ticket_url"),
            ticket_price=show.get("ticket_price"),
            age_restriction=show.get("age_restriction"),
            event_image_url=show.get("event_image_url"),
            notes=show.get("notes"),
            low_confidence=bool(show.get("low_confidence")),
            scrape_status=show.get("scrape_status", "ok"),
            scrape_error=show.get("scrape_error"),
        )

        # insert_show returns None when the show already exists (idempotent)
        if show_id is None:
            with db.get_conn() as conn:
                if show.get("raw_title"):
                    row = conn.execute(
                        "SELECT id FROM shows WHERE venue_id=? AND show_date=? AND raw_title=?",
                        (venue_id, show["show_date"], show["raw_title"]),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT id FROM shows WHERE venue_id=? AND event_url=?",
                        (venue_id, show.get("event_url")),
                    ).fetchone()
                show_id = row["id"] if row else None

        if show_id is None:
            continue

        for band_data in show.get("bands", []):
            band_id, _ = db.get_or_create_band(band_data["name"])

            genres_raw = band_data.get("spotify_genres")
            genres = json.loads(genres_raw) if genres_raw else []

            other_raw = band_data.get("other_urls")
            other_urls = json.loads(other_raw) if other_raw else []

            result = BandResult(
                name=band_data["name"],
                spotify_id=band_data.get("spotify_id"),
                spotify_url=band_data.get("spotify_url"),
                spotify_genres=genres,
                spotify_followers=band_data.get("spotify_followers"),
                spotify_popularity=band_data.get("spotify_popularity"),
                spotify_image_url=band_data.get("spotify_image_url"),
                spotify_track_count=band_data.get("spotify_track_count"),
                spotify_first_release=band_data.get("spotify_first_release"),
                spotify_last_release=band_data.get("spotify_last_release"),
                bandcamp_url=band_data.get("bandcamp_url"),
                bandcamp_album_id=band_data.get("bandcamp_album_id"),
                bandcamp_snippet=band_data.get("bandcamp_snippet"),
                bandcamp_title=band_data.get("bandcamp_title"),
                instagram_url=band_data.get("instagram_url"),
                instagram_snippet=band_data.get("instagram_snippet"),
                instagram_title=band_data.get("instagram_title"),
                other_urls=other_urls,
                google_general_url=band_data.get("google_general_url") or "",
                google_spotify_url=band_data.get("google_spotify_url") or "",
                google_bandcamp_url=band_data.get("google_bandcamp_url") or "",
                google_instagram_url=band_data.get("google_instagram_url") or "",
                lookup_status=band_data.get("lookup_status", "done"),
                lookup_error=band_data.get("lookup_error"),
            )
            db.update_band_lookup(band_id, result)
            db.link_show_band(show_id, band_id, band_data.get("position", 0))

    print(f"Imported {len(shows)} shows from {input_path}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else CACHE_PATH

    if cmd == "export":
        export_cache(path)
    elif cmd == "import":
        import_cache(path)
    else:
        print("Usage: cache.py export|import [path]", file=sys.stderr)
        sys.exit(1)
