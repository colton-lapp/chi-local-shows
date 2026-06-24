import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from models import BandResult

DB_PATH = Path(__file__).parent / "shows.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS venues (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    address     TEXT,
    description TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shows (
    id            INTEGER PRIMARY KEY,
    venue_id      INTEGER NOT NULL REFERENCES venues(id),
    show_date     TEXT NOT NULL,
    show_time     TEXT,
    raw_title     TEXT,
    event_url     TEXT,
    ticket_url    TEXT,
    scrape_status TEXT NOT NULL DEFAULT 'ok',
    scrape_error  TEXT,
    scraped_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bands (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT NOT NULL,
    name_lower           TEXT NOT NULL UNIQUE,
    spotify_id           TEXT,
    spotify_url          TEXT,
    spotify_genres       TEXT,
    spotify_followers    INTEGER,
    spotify_popularity   INTEGER,
    spotify_image_url    TEXT,
    bandcamp_url         TEXT,
    instagram_url        TEXT,
    other_urls           TEXT,
    google_general_url   TEXT,
    google_spotify_url   TEXT,
    google_bandcamp_url  TEXT,
    google_instagram_url TEXT,
    lookup_status        TEXT NOT NULL DEFAULT 'pending',
    lookup_error         TEXT,
    looked_up_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS show_bands (
    show_id  INTEGER NOT NULL REFERENCES shows(id),
    band_id  INTEGER NOT NULL REFERENCES bands(id),
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (show_id, band_id)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id          INTEGER PRIMARY KEY,
    venue_id    INTEGER NOT NULL REFERENCES venues(id),
    run_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status      TEXT NOT NULL,
    shows_found INTEGER NOT NULL DEFAULT 0,
    error_msg   TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after initial schema. Safe to call repeatedly."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bands)").fetchall()}
    new_cols = [
        ("bandcamp_url", "TEXT"),
        ("instagram_url", "TEXT"),
        ("other_urls", "TEXT"),
        ("bandcamp_album_id", "TEXT"),
        ("spotify_track_count", "INTEGER"),
        ("spotify_first_release", "TEXT"),
        ("spotify_last_release", "TEXT"),
    ]
    # shows table additions
    existing_shows = {row[1] for row in conn.execute("PRAGMA table_info(shows)").fetchall()}
    new_show_cols = [
        ("ticket_price", "TEXT"),
        ("age_restriction", "TEXT"),
        ("event_image_url", "TEXT"),
        ("notes", "TEXT"),
        ("low_confidence", "INTEGER"),
    ]
    for col, typ in new_show_cols:
        if col not in existing_shows:
            conn.execute(f"ALTER TABLE shows ADD COLUMN {col} {typ}")
    for col, typ in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE bands ADD COLUMN {col} {typ}")


def upsert_venue(name: str, address: str | None = None, description: str | None = None) -> int:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO venues (name, address, description)
               VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET address=excluded.address, description=excluded.description""",
            (name, address, description),
        )
        row = conn.execute("SELECT id FROM venues WHERE name=?", (name,)).fetchone()
        return row["id"]


def get_or_create_band(name: str) -> tuple[int, bool]:
    """Returns (band_id, created). Deduplicates by lowercase name."""
    name_lower = name.lower().strip()
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM bands WHERE name_lower=?", (name_lower,)).fetchone()
        if row:
            return row["id"], False

        q = quote_plus(name)
        cursor = conn.execute(
            """INSERT INTO bands (name, name_lower,
               google_general_url, google_spotify_url, google_bandcamp_url, google_instagram_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                name,
                name_lower,
                f"https://www.google.com/search?q={q}+Chicago+band",
                f"https://www.google.com/search?q={q}+site:open.spotify.com",
                f"https://www.google.com/search?q={q}+site:bandcamp.com",
                f"https://www.google.com/search?q={q}+site:instagram.com",
            ),
        )
        return cursor.lastrowid, True


def insert_show(
    venue_id: int,
    show_date: str,
    show_time: str | None,
    raw_title: str | None,
    event_url: str | None,
    ticket_url: str | None,
    ticket_price: str | None = None,
    age_restriction: str | None = None,
    event_image_url: str | None = None,
    notes: str | None = None,
    low_confidence: bool = False,
    scrape_status: str = "ok",
    scrape_error: str | None = None,
) -> int | None:
    """Insert a show. Returns new id, or None if duplicate (idempotent)."""
    with get_conn() as conn:
        # Prefer title+date as the dedup key — event_url is often a venue homepage
        # shared across many shows (e.g. Empty Bottle) and can't be used as a unique id.
        if raw_title:
            existing = conn.execute(
                "SELECT id FROM shows WHERE venue_id=? AND show_date=? AND raw_title=?",
                (venue_id, show_date, raw_title),
            ).fetchone()
        elif event_url:
            existing = conn.execute(
                "SELECT id FROM shows WHERE venue_id=? AND event_url=?",
                (venue_id, event_url),
            ).fetchone()
        else:
            existing = None

        if existing:
            return None

        cursor = conn.execute(
            """INSERT INTO shows
               (venue_id, show_date, show_time, raw_title, event_url, ticket_url,
                ticket_price, age_restriction, event_image_url, notes, low_confidence,
                scrape_status, scrape_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (venue_id, show_date, show_time, raw_title, event_url, ticket_url,
             ticket_price, age_restriction, event_image_url, notes, int(low_confidence),
             scrape_status, scrape_error),
        )
        return cursor.lastrowid


def link_show_band(show_id: int, band_id: int, position: int = 0) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO show_bands (show_id, band_id, position) VALUES (?, ?, ?)",
            (show_id, band_id, position),
        )


def log_scrape(venue_id: int, status: str, shows_found: int = 0, error_msg: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scrape_log (venue_id, status, shows_found, error_msg) VALUES (?, ?, ?, ?)",
            (venue_id, status, shows_found, error_msg),
        )


def get_band(band_id: int) -> sqlite3.Row:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM bands WHERE id=?", (band_id,)).fetchone()


def get_bands_needing_lookup(retry_errors: bool = False) -> list[sqlite3.Row]:
    statuses = ["pending", "error"] if retry_errors else ["pending"]
    placeholders = ",".join("?" * len(statuses))
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM bands WHERE lookup_status IN ({placeholders}) ORDER BY id",
            statuses,
        ).fetchall()


def update_band_lookup(band_id: int, result: BandResult) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE bands SET
               spotify_id=?, spotify_url=?, spotify_genres=?,
               spotify_followers=?, spotify_popularity=?, spotify_image_url=?,
               spotify_track_count=?, spotify_first_release=?, spotify_last_release=?,
               bandcamp_url=?, bandcamp_album_id=?, instagram_url=?, other_urls=?,
               google_general_url=?, google_spotify_url=?,
               google_bandcamp_url=?, google_instagram_url=?,
               lookup_status=?, lookup_error=?, looked_up_at=?
               WHERE id=?""",
            (
                result.spotify_id,
                result.spotify_url,
                json.dumps(result.spotify_genres),
                result.spotify_followers,
                result.spotify_popularity,
                result.spotify_image_url,
                result.spotify_track_count,
                result.spotify_first_release,
                result.spotify_last_release,
                result.bandcamp_url,
                result.bandcamp_album_id,
                result.instagram_url,
                json.dumps(result.other_urls),
                result.google_general_url,
                result.google_spotify_url,
                result.google_bandcamp_url,
                result.google_instagram_url,
                result.lookup_status,
                result.lookup_error,
                datetime.now().isoformat(),
                band_id,
            ),
        )


def get_shows_in_range(start: str, end: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT s.*, v.name as venue_name
               FROM shows s JOIN venues v ON s.venue_id = v.id
               WHERE s.show_date BETWEEN ? AND ?
               ORDER BY s.show_date, s.show_time""",
            (start, end),
        ).fetchall()


def get_bands_for_show(show_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT b.*, sb.position
               FROM bands b JOIN show_bands sb ON b.id = sb.band_id
               WHERE sb.show_id=?
               ORDER BY sb.position""",
            (show_id,),
        ).fetchall()
