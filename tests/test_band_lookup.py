from band_lookup import build_google_urls, _extract_spotify_artist_id, lookup_band


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


def test_lookup_band_no_spotify_still_has_google_urls(mocker):
    # Patch DuckDuckGo and browser so we don't make network calls
    mocker.patch("band_lookup.find_spotify_url_via_ddg", return_value=None)
    mocker.patch("band_lookup.browser", create=True)

    result = lookup_band("Some Band", sp=None)
    assert result.google_general_url != ""
    assert result.google_bandcamp_url != ""
    assert result.lookup_status == "error"
    assert result.lookup_error is not None


def test_lookup_band_uses_ddg_url(mocker):
    """When DDG finds a Spotify URL and Spotify returns data, result is 'done'."""
    mocker.patch("band_lookup.find_spotify_url_via_ddg",
                 return_value="https://open.spotify.com/artist/ABC123")
    mocker.patch("band_lookup.get_artist_data_from_spotify", return_value={
        "spotify_id": "ABC123",
        "spotify_url": "https://open.spotify.com/artist/ABC123",
        "spotify_genres": ["indie rock"],
        "spotify_followers": 5000,
        "spotify_popularity": 40,
        "spotify_image_url": None,
    })

    mock_sp = mocker.MagicMock()
    result = lookup_band("Some Band", sp=mock_sp)
    assert result.lookup_status == "done"
    assert result.spotify_id == "ABC123"
    assert result.spotify_genres == ["indie rock"]


def test_lookup_band_not_found_when_all_fail(mocker):
    mocker.patch("band_lookup.find_spotify_url_via_ddg", return_value=None)
    mocker.patch("band_lookup.lookup_spotify_direct", return_value=None)
    # Prevent browser import side effects
    mocker.patch("band_lookup.browser", create=True)

    mock_sp = mocker.MagicMock()
    result = lookup_band("Obscure Unknown Band", sp=mock_sp)
    assert result.lookup_status == "not_found"
    assert result.google_general_url != ""
