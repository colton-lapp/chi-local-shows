import json
import pytest
from datetime import date, timedelta

import db
from cache import export_cache, import_cache
from models import BandResult


@pytest.fixture(autouse=True)
def fresh_db(tmp_db):
    pass


def _today_plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# ── export_cache ───────────────────────────────────────────────────────────────

def test_export_cache_empty_db(tmp_path):
    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)
    data = json.loads(cache_path.read_text())
    assert "exported_at" in data
    assert data["shows"] == []


def test_export_cache_with_shows(tmp_path):
    vid = db.upsert_venue("Empty Bottle", "1035 N Western Ave")
    sid = db.insert_show(vid, _today_plus(1), "9PM", "Headliner / Opener", "https://event.com/1", None)
    bid, _ = db.get_or_create_band("Headliner")
    db.update_band_lookup(bid, BandResult(
        name="Headliner",
        spotify_url="https://open.spotify.com/artist/abc",
        spotify_genres=["indie rock"],
        lookup_status="done",
    ))
    db.link_show_band(sid, bid, 0)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)
    data = json.loads(cache_path.read_text())

    assert len(data["shows"]) == 1
    show = data["shows"][0]
    assert show["venue_name"] == "Empty Bottle"
    assert show["raw_title"] == "Headliner / Opener"
    assert len(show["bands"]) == 1
    assert show["bands"][0]["name"] == "Headliner"
    assert show["bands"][0]["spotify_url"] == "https://open.spotify.com/artist/abc"


def test_export_cache_excludes_past_shows(tmp_path):
    vid = db.upsert_venue("Venue")
    db.insert_show(vid, _today_plus(1), None, "Future Show", None, None)
    db.insert_show(vid, _today_plus(-5), None, "Past Show", "https://event.com/past", None)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)
    data = json.loads(cache_path.read_text())

    titles = [s["raw_title"] for s in data["shows"]]
    assert "Future Show" in titles
    assert "Past Show" not in titles


# ── import_cache ───────────────────────────────────────────────────────────────

def test_import_cache_round_trip(tmp_path):
    vid = db.upsert_venue("Subterranean", "2011 W North Ave")
    sid = db.insert_show(
        vid, _today_plus(2), "8PM", "Indie Night",
        "https://subt.net/1", None,
        ticket_price="$12", age_restriction="18+",
    )
    bid1, _ = db.get_or_create_band("Headliner")
    bid2, _ = db.get_or_create_band("Opener")
    db.update_band_lookup(bid1, BandResult(
        name="Headliner",
        spotify_url="https://open.spotify.com/artist/h1",
        spotify_genres=["punk", "indie"],
        spotify_followers=5000,
        bandcamp_url="https://headliner.bandcamp.com",
        instagram_url="https://instagram.com/headliner",
        lookup_status="done",
    ))
    db.update_band_lookup(bid2, BandResult(name="Opener", lookup_status="not_found"))
    db.link_show_band(sid, bid1, 0)
    db.link_show_band(sid, bid2, 1)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)

    db.DB_PATH.unlink()
    import_cache(cache_path)

    shows = db.get_shows_in_range(_today_plus(0), _today_plus(30))
    assert len(shows) == 1
    assert shows[0]["raw_title"] == "Indie Night"
    assert shows[0]["venue_name"] == "Subterranean"
    assert shows[0]["ticket_price"] == "$12"
    assert shows[0]["age_restriction"] == "18+"

    bands = db.get_bands_for_show(shows[0]["id"])
    assert len(bands) == 2
    assert bands[0]["name"] == "Headliner"
    assert bands[0]["spotify_url"] == "https://open.spotify.com/artist/h1"
    assert bands[0]["bandcamp_url"] == "https://headliner.bandcamp.com"
    assert bands[0]["instagram_url"] == "https://instagram.com/headliner"
    assert bands[0]["position"] == 0
    assert bands[1]["name"] == "Opener"
    assert bands[1]["position"] == 1


def test_import_cache_idempotent(tmp_path):
    vid = db.upsert_venue("Venue")
    sid = db.insert_show(vid, _today_plus(1), None, "Show", None, None)
    bid, _ = db.get_or_create_band("Band")
    db.link_show_band(sid, bid, 0)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)

    import_cache(cache_path)
    import_cache(cache_path)

    with db.get_conn() as conn:
        show_count = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
        band_count = conn.execute("SELECT COUNT(*) FROM bands").fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM show_bands").fetchone()[0]
    assert show_count == 1
    assert band_count == 1
    assert link_count == 1


def test_import_cache_no_bands(tmp_path):
    vid = db.upsert_venue("Venue")
    db.insert_show(vid, _today_plus(1), None, "Bandless Show", None, None)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)

    db.DB_PATH.unlink()
    import_cache(cache_path)

    shows = db.get_shows_in_range(_today_plus(0), _today_plus(30))
    assert len(shows) == 1
    assert db.get_bands_for_show(shows[0]["id"]) == []


def test_import_cache_null_spotify_fields(tmp_path):
    vid = db.upsert_venue("Venue")
    sid = db.insert_show(vid, _today_plus(1), None, "Show", None, None)
    bid, _ = db.get_or_create_band("Unknown Band")
    db.update_band_lookup(bid, BandResult(name="Unknown Band", lookup_status="not_found"))
    db.link_show_band(sid, bid, 0)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)

    db.DB_PATH.unlink()
    import_cache(cache_path)

    shows = db.get_shows_in_range(_today_plus(0), _today_plus(30))
    bands = db.get_bands_for_show(shows[0]["id"])
    assert len(bands) == 1
    assert bands[0]["name"] == "Unknown Band"
    assert bands[0]["spotify_url"] is None
    assert bands[0]["lookup_status"] == "not_found"


def test_import_cache_genres_and_other_urls_survive_round_trip(tmp_path):
    vid = db.upsert_venue("Venue")
    sid = db.insert_show(vid, _today_plus(1), None, "Show", None, None)
    bid, _ = db.get_or_create_band("Genre Band")
    db.update_band_lookup(bid, BandResult(
        name="Genre Band",
        spotify_genres=["indie rock", "punk", "lo-fi"],
        other_urls=["https://example.com/1", "https://example.com/2"],
        lookup_status="done",
    ))
    db.link_show_band(sid, bid, 0)

    cache_path = tmp_path / "cache.json"
    export_cache(cache_path)

    db.DB_PATH.unlink()
    import_cache(cache_path)

    shows = db.get_shows_in_range(_today_plus(0), _today_plus(30))
    bands = db.get_bands_for_show(shows[0]["id"])
    genres = json.loads(bands[0]["spotify_genres"])
    other = json.loads(bands[0]["other_urls"])
    assert genres == ["indie rock", "punk", "lo-fi"]
    assert other == ["https://example.com/1", "https://example.com/2"]
