from band_lookup import (
    build_google_urls,
    _extract_spotify_artist_id,
    _classify_results,
    lookup_band,
)


# ── URL utilities ─────────────────────────────────────────────────────────────

def test_build_google_urls_contains_band_name():
    urls = build_google_urls("Test Band")
    assert "Test" in urls["google_general_url"]


def test_build_google_urls_chicago():
    urls = build_google_urls("Deeper")
    assert "Chicago" in urls["google_general_url"]


def test_build_google_urls_platform_sites():
    urls = build_google_urls("Deeper")
    assert "bandcamp.com" in urls["google_bandcamp_url"]
    assert "instagram.com" in urls["google_instagram_url"]
    assert "spotify.com" in urls["google_spotify_url"]


def test_extract_spotify_artist_id_valid():
    url = "https://open.spotify.com/artist/2cFrymmkijnjDg9SS92EPM"
    assert _extract_spotify_artist_id(url) == "2cFrymmkijnjDg9SS92EPM"


def test_extract_spotify_artist_id_no_match():
    assert _extract_spotify_artist_id("https://spotify.com/track/abc") is None
    assert _extract_spotify_artist_id("https://example.com") is None


# ── _classify_results ─────────────────────────────────────────────────────────

def test_classify_results_extracts_spotify():
    results = [{"href": "https://open.spotify.com/artist/ABC123"}]
    found = _classify_results(results)
    assert found["spotify_url"] == "https://open.spotify.com/artist/ABC123"


def test_classify_results_extracts_instagram():
    results = [{"href": "https://www.instagram.com/somebandchicago"}]
    found = _classify_results(results)
    assert found["instagram_url"] == "https://www.instagram.com/somebandchicago"


def test_classify_results_extracts_bandcamp():
    results = [{"href": "https://someband.bandcamp.com/"}]
    found = _classify_results(results)
    assert found["bandcamp_url"] == "https://someband.bandcamp.com/"


def test_classify_results_all_types():
    results = [
        {"href": "https://open.spotify.com/artist/ABC123"},
        {"href": "https://theband.bandcamp.com"},
        {"href": "https://instagram.com/theband"},
        {"href": "https://theband.com"},
    ]
    found = _classify_results(results)
    assert found["spotify_url"] is not None
    assert found["bandcamp_url"] is not None
    assert found["instagram_url"] is not None
    assert len(found["other_urls"]) == 1


def test_classify_results_limits_other_urls_to_five():
    results = [{"href": f"https://site{i}.com/band"} for i in range(10)]
    found = _classify_results(results)
    assert len(found["other_urls"]) == 5


def test_classify_results_excludes_search_engines():
    results = [
        {"href": "https://google.com/search?q=band"},
        {"href": "https://bing.com/search?q=band"},
        {"href": "https://realsite.com/band"},
    ]
    found = _classify_results(results)
    assert len(found["other_urls"]) == 1
    assert "realsite.com" in found["other_urls"][0]


def test_classify_results_empty():
    found = _classify_results([])
    assert found == {"spotify_url": None, "instagram_url": None, "bandcamp_url": None, "other_urls": []}


# ── lookup_band ───────────────────────────────────────────────────────────────

def _no_social():
    return {"spotify_url": None, "instagram_url": None, "bandcamp_url": None, "other_urls": []}


def test_lookup_band_no_spotify_client_still_has_google_urls(mocker):
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value=_no_social())
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Some Band", sp=None)
    assert result.google_general_url != ""
    assert result.google_bandcamp_url != ""
    assert result.lookup_status == "error"
    assert result.lookup_error is not None


def test_lookup_band_uses_ddg_spotify_url(mocker):
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": None,
        "other_urls": ["https://theband.com"],
    })
    mocker.patch("band_lookup.get_artist_data_from_spotify", return_value={
        "spotify_id": "ABC123",
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "spotify_genres": ["indie rock"],
        "spotify_followers": 5000,
        "spotify_popularity": 40,
        "spotify_image_url": None,
    })
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.lookup_status == "done"
    assert result.spotify_id == "ABC123"
    assert result.instagram_url == "https://instagram.com/theband"
    assert result.other_urls == ["https://theband.com"]


def test_lookup_band_not_found_when_all_searches_fail(mocker):
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value=_no_social())
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Obscure Unknown Band", sp=mocker.MagicMock())
    assert result.lookup_status == "not_found"
    assert result.google_general_url != ""


def test_lookup_band_done_when_only_instagram_found(mocker):
    """lookup_status is 'done' even when only social links (no Spotify) are found."""
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": None,
        "other_urls": [],
    })
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.lookup_status == "done"
    assert result.instagram_url == "https://instagram.com/theband"
    assert result.spotify_url is None


def test_lookup_band_bandcamp_populated(mocker):
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": None,
        "instagram_url": None,
        "bandcamp_url": "https://theband.bandcamp.com",
        "other_urls": [],
    })
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("The Band", sp=mocker.MagicMock())
    assert result.bandcamp_url == "https://theband.bandcamp.com"
    assert result.lookup_status == "done"
