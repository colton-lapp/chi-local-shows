import pytest
import db


@pytest.fixture(autouse=True)
def fresh_db(tmp_db):
    pass


def test_upsert_venue_creates():
    vid = db.upsert_venue("Test Venue", "123 Main St", "A venue")
    assert vid > 0


def test_upsert_venue_is_idempotent():
    vid1 = db.upsert_venue("Test Venue", "123 Main St", "A venue")
    vid2 = db.upsert_venue("Test Venue", "456 Other St", "Updated")
    assert vid1 == vid2


def test_get_or_create_band_creates():
    bid, created = db.get_or_create_band("Test Band")
    assert created is True
    assert bid > 0


def test_get_or_create_band_deduplicates_case_insensitive():
    bid1, _ = db.get_or_create_band("Test Band")
    bid2, created = db.get_or_create_band("test band")
    assert created is False
    assert bid1 == bid2


def test_get_or_create_band_sets_google_urls():
    bid, _ = db.get_or_create_band("Deeper")
    band = db.get_band(bid)
    assert "Deeper" in band["google_general_url"]
    assert "Chicago" in band["google_general_url"]
    assert "bandcamp" in band["google_bandcamp_url"]
    assert "instagram" in band["google_instagram_url"]


def test_insert_show_deduplicates_by_event_url():
    vid = db.upsert_venue("Venue")
    sid1 = db.insert_show(vid, "2026-06-25", "9PM", "Title", "https://event.com/1", None)
    sid2 = db.insert_show(vid, "2026-06-25", "9PM", "Title", "https://event.com/1", None)
    assert sid1 is not None
    assert sid2 is None


def test_insert_show_deduplicates_by_date_and_title():
    vid = db.upsert_venue("Venue")
    sid1 = db.insert_show(vid, "2026-06-25", "9PM", "Same Title", None, None)
    sid2 = db.insert_show(vid, "2026-06-25", "9PM", "Same Title", None, None)
    assert sid1 is not None
    assert sid2 is None


def test_insert_show_different_titles_both_inserted():
    vid = db.upsert_venue("Venue")
    sid1 = db.insert_show(vid, "2026-06-25", "9PM", "Band A", None, None)
    sid2 = db.insert_show(vid, "2026-06-25", "9PM", "Band B", None, None)
    assert sid1 is not None
    assert sid2 is not None
    assert sid1 != sid2


def test_link_show_band_is_idempotent():
    vid = db.upsert_venue("Venue")
    bid, _ = db.get_or_create_band("Band")
    sid = db.insert_show(vid, "2026-06-25", None, "Show", None, None)
    db.link_show_band(sid, bid, 0)
    db.link_show_band(sid, bid, 0)  # should not raise
    bands = db.get_bands_for_show(sid)
    assert len(bands) == 1


def test_get_bands_needing_lookup_returns_pending():
    db.get_or_create_band("Band A")
    db.get_or_create_band("Band B")
    pending = db.get_bands_needing_lookup()
    assert len(pending) == 2


def test_get_bands_needing_lookup_excludes_done():
    from models import BandResult
    from band_lookup import build_google_urls
    bid, _ = db.get_or_create_band("Done Band")
    result = BandResult(name="Done Band", lookup_status="done", **build_google_urls("Done Band"))
    db.update_band_lookup(bid, result)
    pending = db.get_bands_needing_lookup()
    assert len(pending) == 0


def test_get_bands_needing_lookup_retry_errors():
    from models import BandResult
    from band_lookup import build_google_urls
    bid, _ = db.get_or_create_band("Error Band")
    result = BandResult(name="Error Band", lookup_status="error", lookup_error="timeout", **build_google_urls("Error Band"))
    db.update_band_lookup(bid, result)
    assert len(db.get_bands_needing_lookup()) == 0
    assert len(db.get_bands_needing_lookup(retry_errors=True)) == 1
