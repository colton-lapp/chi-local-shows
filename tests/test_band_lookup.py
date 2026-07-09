import band_lookup
from band_lookup import (
    build_google_urls,
    _extract_spotify_artist_id,
    _classify_results,
    _match_score,
    _merge_found,
    _serper_search,
    find_band_urls_via_serper,
    serper_configured,
    scrape_bandcamp_album_id,
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


# ── scrape_bandcamp_album_id ──────────────────────────────────────────────────

_ALBUM_HTML = """
<html><head>
<meta name="bc-page-properties" content='{"item_type":"a","item_id":123456789}'>
</head><body></body></html>
"""

_TRACK_HTML = """
<html><head>
<meta name="bc-page-properties" content='{"item_type":"t","item_id":987654321}'>
</head><body></body></html>
"""

_BAND_WITH_GRID_HTML = """
<html><head>
<meta name="bc-page-properties" content='{"item_type":"b","item_id":555}'>
</head><body>
<ol id="music-grid">
  <li><a href="/album/latest-release">Latest</a></li>
</ol>
</body></html>
"""

_BAND_NO_GRID_HTML = """
<html><head>
<meta name="bc-page-properties" content='{"item_type":"b","item_id":555}'>
</head><body><p>Custom homepage, no release grid here</p></body></html>
"""

_NO_META_HTML = "<html><head></head><body>nothing here</body></html>"


def _fake_resp(mocker, html, ok=True, status=200):
    resp = mocker.MagicMock()
    resp.ok = ok
    resp.status_code = status
    resp.text = html
    return resp


def test_scrape_bandcamp_album_id_direct_album_url(mocker):
    mocker.patch("band_lookup.requests.get", return_value=_fake_resp(mocker, _ALBUM_HTML))
    assert scrape_bandcamp_album_id("https://theband.bandcamp.com/album/some-album") == "123456789"


def test_scrape_bandcamp_album_id_direct_track_url(mocker):
    mocker.patch("band_lookup.requests.get", return_value=_fake_resp(mocker, _TRACK_HTML))
    assert scrape_bandcamp_album_id("https://theband.bandcamp.com/track/some-track") == "987654321"


def test_scrape_bandcamp_album_id_follows_music_grid_link(mocker):
    band_resp = _fake_resp(mocker, _BAND_WITH_GRID_HTML)
    album_resp = _fake_resp(mocker, _ALBUM_HTML)
    get_mock = mocker.patch("band_lookup.requests.get", side_effect=[band_resp, album_resp])
    result = scrape_bandcamp_album_id("https://theband.bandcamp.com/")
    assert result == "123456789"
    assert get_mock.call_count == 2
    assert get_mock.call_args_list[1].args[0] == "https://theband.bandcamp.com/album/latest-release"


def test_scrape_bandcamp_album_id_falls_back_to_music_listing(mocker):
    home_resp = _fake_resp(mocker, _BAND_NO_GRID_HTML)
    music_resp = _fake_resp(mocker, _BAND_WITH_GRID_HTML)
    album_resp = _fake_resp(mocker, _ALBUM_HTML)
    get_mock = mocker.patch("band_lookup.requests.get", side_effect=[home_resp, music_resp, album_resp])
    result = scrape_bandcamp_album_id("https://theband.bandcamp.com")
    assert result == "123456789"
    assert get_mock.call_args_list[1].args[0] == "https://theband.bandcamp.com/music"


def test_scrape_bandcamp_album_id_returns_none_when_no_meta_tag(mocker):
    mocker.patch("band_lookup.requests.get", return_value=_fake_resp(mocker, _NO_META_HTML))
    assert scrape_bandcamp_album_id("https://theband.bandcamp.com/album/x") is None


def test_scrape_bandcamp_album_id_returns_none_on_http_error(mocker):
    mocker.patch("band_lookup.requests.get", return_value=_fake_resp(mocker, "", ok=False, status=404))
    assert scrape_bandcamp_album_id("https://theband.bandcamp.com/") is None


def test_scrape_bandcamp_uses_browser_like_user_agent():
    ua = band_lookup._SCRAPE_HEADERS["User-Agent"]
    assert "compatible" not in ua
    assert "Chrome" in ua


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


def test_classify_results_captures_instagram_snippet_and_title():
    results = [{
        "href": "https://www.instagram.com/somebandchicago",
        "snippet": "1,204 Followers, 88 Following, 42 Posts",
        "title": "Some Band Chicago (@somebandchicago) • Instagram",
    }]
    found = _classify_results(results)
    assert found["instagram_snippet"] == "1,204 Followers, 88 Following, 42 Posts"
    assert found["instagram_title"] == "Some Band Chicago (@somebandchicago) • Instagram"


def test_classify_results_no_snippet_when_result_lacks_one():
    """Bing/DDG results never carry snippet/title — should stay None, not KeyError."""
    results = [{"href": "https://www.instagram.com/somebandchicago"}]
    found = _classify_results(results)
    assert found["instagram_snippet"] is None
    assert found["instagram_title"] is None


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
    assert found == {
        "spotify_url": None,
        "instagram_url": None, "instagram_snippet": None, "instagram_title": None,
        "bandcamp_url": None, "bandcamp_snippet": None, "bandcamp_title": None,
        "other_urls": [],
    }


# ── _match_score ──────────────────────────────────────────────────────────────

def test_match_score_exact_name_low_followers_accepted():
    score = _match_score("Deeper", "Deeper", followers=1200, genres=["post-punk"])
    assert score >= 2


def test_match_score_rejects_substring_match():
    """A search result whose name merely contains the query (or vice versa)
    should never be treated as a match — this is the 'Yucki' vs 'Yucki Gross'
    and 'Halo' vs 'Southern Halo' false-positive pattern."""
    assert _match_score("Yucki Gross", "Yucki", followers=1000, genres=[]) is None
    assert _match_score("Halo", "Southern Halo", followers=1000, genres=[]) is None
    assert _match_score("Janne", "Janne Moreno", followers=1000, genres=[]) is None


def test_match_score_rejects_high_followers_even_if_exact():
    score = _match_score("Common Name Band", "Common Name Band", followers=500_000, genres=[])
    assert score < 2


def test_match_score_rejects_foreign_signals_combined_with_fuzzy_match():
    fuzzy_name = "The Midnight Colective"  # trivial typo, not an exact match
    score = _match_score("The Midnight Collective", fuzzy_name, followers=30_000, genres=["k-pop"])
    assert score is not None and score < 2


def test_match_score_exact_match_with_foreign_genre_alone_still_accepted():
    """A legitimately-matched, low-follower band shouldn't be rejected just for
    having a genre tag that sounds non-US (e.g. a Chicago Latin band)."""
    score = _match_score("Grupo Fantasma", "Grupo Fantasma", followers=1000, genres=["latin"])
    assert score >= 2


# ── Serper / _merge_found ───────────────────────────────────────────────────

def _no_social():
    return {
        "spotify_url": None,
        "instagram_url": None, "instagram_snippet": None, "instagram_title": None,
        "bandcamp_url": None, "bandcamp_snippet": None, "bandcamp_title": None,
        "other_urls": [],
    }


def test_serper_search_returns_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert _serper_search("some query") == []


def test_serper_search_parses_items(monkeypatch, mocker):
    monkeypatch.setenv("SERPER_API_KEY", "key")
    mock_resp = mocker.MagicMock()
    mock_resp.json.return_value = {"organic": [{"link": "https://open.spotify.com/artist/ABC123"}]}
    mocker.patch("band_lookup.requests.post", return_value=mock_resp)
    results = _serper_search("some query")
    assert results == [{"href": "https://open.spotify.com/artist/ABC123", "snippet": None, "title": None}]


def test_find_band_urls_via_serper_no_op_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert find_band_urls_via_serper("Some Band") == _no_social()


def test_serper_configured_reflects_env(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert serper_configured() is False
    monkeypatch.setenv("SERPER_API_KEY", "key")
    assert serper_configured() is True


def test_serper_search_records_error_stats(monkeypatch, mocker):
    band_lookup.reset_stats()
    monkeypatch.setenv("SERPER_API_KEY", "key")
    mocker.patch("band_lookup.requests.post", side_effect=Exception("boom"))
    assert _serper_search("q") == []
    assert band_lookup.stats["serper_queries"] == 1
    assert band_lookup.stats["serper_errors"] == 1
    assert "boom" in band_lookup.stats["serper_last_error"]


def test_serper_search_disables_after_repeated_errors(monkeypatch, mocker):
    band_lookup.reset_stats()
    monkeypatch.setenv("SERPER_API_KEY", "key")
    post_mock = mocker.patch("band_lookup.requests.post", side_effect=Exception("boom"))
    for _ in range(band_lookup._SERPER_MAX_ERRORS):
        _serper_search("q")
    assert band_lookup.stats["serper_disabled_reason"] is not None
    assert post_mock.call_count == band_lookup._SERPER_MAX_ERRORS

    # Once disabled, further calls skip the request entirely for the rest of the run
    _serper_search("q")
    assert post_mock.call_count == band_lookup._SERPER_MAX_ERRORS


def test_merge_found_fills_empty_fields_only():
    dst = {"spotify_url": "https://open.spotify.com/artist/ABC", "instagram_url": None,
           "bandcamp_url": None, "other_urls": []}
    src = {"spotify_url": "https://open.spotify.com/artist/XYZ",
           "instagram_url": "https://instagram.com/theband",
           "bandcamp_url": "https://theband.bandcamp.com", "other_urls": ["https://theband.com"]}
    merged = _merge_found(dst, src)
    assert merged["spotify_url"] == "https://open.spotify.com/artist/ABC"  # not overwritten
    assert merged["instagram_url"] == "https://instagram.com/theband"
    assert merged["bandcamp_url"] == "https://theband.bandcamp.com"
    assert merged["other_urls"] == ["https://theband.com"]


def test_merge_found_carries_snippet_and_title_alongside_url():
    dst = {"spotify_url": None, "instagram_url": None, "bandcamp_url": None, "other_urls": []}
    src = {
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "instagram_snippet": "A Chicago band.",
        "instagram_title": "The Band (@theband) • Instagram",
        "bandcamp_url": None,
        "other_urls": [],
    }
    merged = _merge_found(dst, src)
    assert merged["instagram_snippet"] == "A Chicago band."
    assert merged["instagram_title"] == "The Band (@theband) • Instagram"


def test_merge_found_does_not_overwrite_existing_url_snippet_with_later_tier():
    dst = {
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "instagram_snippet": "Found by Serper.",
        "instagram_title": None,
        "bandcamp_url": None,
        "other_urls": [],
    }
    src = {
        "spotify_url": None,
        "instagram_url": "https://instagram.com/other-match",
        "instagram_snippet": "Found by Bing (should be ignored).",
        "instagram_title": None,
        "bandcamp_url": None,
        "other_urls": [],
    }
    merged = _merge_found(dst, src)
    assert merged["instagram_url"] == "https://instagram.com/theband"
    assert merged["instagram_snippet"] == "Found by Serper."


# ── lookup_band ───────────────────────────────────────────────────────────────


def test_lookup_band_no_spotify_client_still_has_google_urls(mocker):
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value=_no_social())
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Some Band", sp=None)
    assert result.google_general_url != ""
    assert result.google_bandcamp_url != ""
    assert result.lookup_status == "error"
    assert result.lookup_error is not None


def test_lookup_band_uses_ddg_spotify_url(mocker):
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": None,
        "other_urls": ["https://theband.com"],
    })
    mocker.patch("browser.is_available", return_value=False)
    mocker.patch("band_lookup.get_artist_data_from_spotify", return_value={
        "_name": "Some Band",
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
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value=_no_social())
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Obscure Unknown Band", sp=mocker.MagicMock())
    assert result.lookup_status == "not_found"
    assert result.google_general_url != ""


def test_lookup_band_done_when_only_instagram_found(mocker):
    """lookup_status is 'done' even when only social links (no Spotify) are found."""
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
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
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
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


def test_lookup_band_uses_serper_result_without_ddg_or_bing(mocker):
    """When Serper finds everything, Bing and DDG should never be invoked."""
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value={
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": "https://theband.bandcamp.com",
        "other_urls": [],
    })
    ddg_mock = mocker.patch("band_lookup.find_band_urls_via_ddg")
    browser_available_mock = mocker.patch("browser.is_available")
    mocker.patch("band_lookup.get_artist_data_from_spotify", return_value={
        "_name": "Some Band",
        "spotify_id": "ABC123",
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "spotify_genres": ["indie rock"],
        "spotify_followers": 5000,
        "spotify_popularity": 40,
        "spotify_image_url": None,
    })
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.instagram_url == "https://instagram.com/theband"
    assert result.bandcamp_url == "https://theband.bandcamp.com"
    ddg_mock.assert_not_called()
    browser_available_mock.assert_not_called()


def test_lookup_band_populates_instagram_and_bandcamp_previews_from_serper(mocker):
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value={
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "instagram_snippet": "1,204 Followers, 88 Following, 42 Posts",
        "instagram_title": "The Band (@theband) • Instagram",
        "bandcamp_url": "https://theband.bandcamp.com",
        "bandcamp_snippet": "Chicago post-punk trio.",
        "bandcamp_title": "The Band | Chicago, Illinois",
        "other_urls": [],
    })
    mocker.patch("band_lookup.scrape_bandcamp_album_id", return_value=None)
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.instagram_snippet == "1,204 Followers, 88 Following, 42 Posts"
    assert result.instagram_title == "The Band (@theband) • Instagram"
    assert result.bandcamp_snippet == "Chicago post-punk trio."
    assert result.bandcamp_title == "The Band | Chicago, Illinois"


def test_lookup_band_previews_none_when_tier_provides_no_snippet(mocker):
    """Bing/DDG-sourced links have no snippet/title — fields should stay None, not error."""
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": None,
        "other_urls": [],
    })
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.instagram_url == "https://instagram.com/theband"
    assert result.instagram_snippet is None
    assert result.instagram_title is None


def test_lookup_band_merges_bing_and_ddg_when_serper_finds_nothing(mocker):
    """Fields found by Bing should not be overwritten by a later DDG pass."""
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("browser.is_available", return_value=True)
    mocker.patch("browser.search_bing_urls", return_value={
        "spotify_url": None,
        "instagram_url": "https://instagram.com/theband",
        "bandcamp_url": None,
        "other_urls": [],
    })
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": None,
        "instagram_url": None,
        "bandcamp_url": "https://theband.bandcamp.com",
        "other_urls": [],
    })
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    result = lookup_band("Some Band", sp=mocker.MagicMock())
    assert result.instagram_url == "https://instagram.com/theband"
    assert result.bandcamp_url == "https://theband.bandcamp.com"


# ── stats tracking ────────────────────────────────────────────────────────────

def test_lookup_band_records_serper_hit_when_configured(monkeypatch, mocker):
    band_lookup.reset_stats()
    monkeypatch.setenv("SERPER_API_KEY", "key")
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value={
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "instagram_url": None,
        "bandcamp_url": None,
        "other_urls": [],
    })
    mocker.patch("band_lookup.get_artist_data_from_spotify", return_value={
        "_name": "Some Band", "spotify_id": "ABC123",
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "spotify_genres": [], "spotify_followers": 100, "spotify_popularity": 10,
        "spotify_image_url": None,
    })
    lookup_band("Some Band", sp=mocker.MagicMock())
    assert band_lookup.stats["serper_bands_hit"] == 1
    assert band_lookup.stats["bands_spotify_matched"] == 1
    assert band_lookup.stats["bands_total"] == 1


def test_lookup_band_no_serper_hit_when_unconfigured(monkeypatch, mocker):
    band_lookup.reset_stats()
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value=_no_social())
    mocker.patch("browser.is_available", return_value=False)
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    lookup_band("Some Band", sp=mocker.MagicMock())
    assert band_lookup.stats["serper_bands_hit"] == 0
    assert band_lookup.stats["bands_not_found"] == 1


def test_lookup_band_records_bandcamp_scrape_stats(mocker):
    band_lookup.reset_stats()
    mocker.patch("band_lookup.find_band_urls_via_serper", return_value=_no_social())
    mocker.patch("band_lookup.find_band_urls_via_ddg", return_value={
        "spotify_url": None, "instagram_url": None,
        "bandcamp_url": "https://theband.bandcamp.com", "other_urls": [],
    })
    mocker.patch("band_lookup.scrape_bandcamp_album_id", return_value=None)
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    mocker.patch("browser.is_available", return_value=False)
    lookup_band("The Band", sp=mocker.MagicMock())
    assert band_lookup.stats["bandcamp_urls_found"] == 1
    assert band_lookup.stats["bandcamp_album_ids_scraped"] == 0
