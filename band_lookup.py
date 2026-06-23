"""
Band lookup: find a band's Spotify profile and construct Google search fallback URLs.

Primary approach: DuckDuckGo search for "{band}" site:open.spotify.com chicago
  → extracts Spotify artist URL → fetches artist data via Spotify API
  → more accurate than Spotify API direct search for local/obscure bands

Fallback: Spotify API direct artist search (broader but less contextual)
"""
import logging
import re
import time
from urllib.parse import quote_plus

import spotipy

from models import BandResult

log = logging.getLogger(__name__)

# Delay between DuckDuckGo searches to avoid rate limiting
DDGS_SLEEP = 1.5


def build_google_urls(band_name: str) -> dict:
    """Always returns Google search URLs. Never fails."""
    q = quote_plus(band_name)
    return {
        "google_general_url": f"https://www.google.com/search?q={q}+Chicago+band",
        "google_spotify_url": f"https://www.google.com/search?q={q}+site:open.spotify.com",
        "google_bandcamp_url": f"https://www.google.com/search?q={q}+site:bandcamp.com",
        "google_instagram_url": f"https://www.google.com/search?q={q}+site:instagram.com",
    }


def _extract_spotify_artist_id(url: str) -> str | None:
    match = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", url)
    return match.group(1) if match else None


def find_spotify_url_via_ddg(band_name: str) -> str | None:
    """
    Search DuckDuckGo for the band's Spotify artist page, biased toward Chicago.
    Returns the Spotify artist URL if found, else None.
    """
    try:
        from duckduckgo_search import DDGS

        query = f'"{band_name}" site:open.spotify.com/artist chicago'
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        time.sleep(DDGS_SLEEP)

        for r in results:
            url = r.get("href", "")
            if _extract_spotify_artist_id(url):
                return url

        # Retry without quotes if quoted search found nothing
        query_bare = f"{band_name} site:open.spotify.com/artist chicago"
        with DDGS() as ddgs:
            results = list(ddgs.text(query_bare, max_results=5))
        time.sleep(DDGS_SLEEP)

        for r in results:
            url = r.get("href", "")
            if _extract_spotify_artist_id(url):
                return url

    except Exception as e:
        log.debug(f"DuckDuckGo search failed for '{band_name}': {e}")

    return None


def get_artist_data_from_spotify(artist_id: str, sp: spotipy.Spotify) -> dict | None:
    """Fetch artist data from Spotify API using a known artist ID."""
    try:
        artist = sp.artist(artist_id)
        return {
            "spotify_id": artist["id"],
            "spotify_url": artist["external_urls"]["spotify"],
            "spotify_genres": artist.get("genres", []),
            "spotify_followers": artist["followers"]["total"],
            "spotify_popularity": artist["popularity"],
            "spotify_image_url": artist["images"][0]["url"] if artist.get("images") else None,
        }
    except Exception as e:
        log.debug(f"Spotify artist fetch failed for ID '{artist_id}': {e}")
        return None


def lookup_spotify_direct(band_name: str, sp: spotipy.Spotify) -> dict | None:
    """
    Fallback: search Spotify API directly. Less context-aware than Google search.
    Applies a loose name-match confidence check to avoid wrong-artist matches.
    """
    try:
        results = sp.search(q=f"artist:{band_name}", type="artist", limit=5)
        items = results.get("artists", {}).get("items", [])
    except Exception as e:
        log.debug(f"Spotify API search failed for '{band_name}': {e}")
        return None

    if not items:
        return None

    band_lower = band_name.lower().strip()
    best = None
    for artist in items:
        a_lower = artist["name"].lower().strip()
        if a_lower == band_lower:
            best = artist
            break
        if a_lower in band_lower or band_lower in a_lower:
            best = artist

    if best is None:
        log.debug(f"No confident Spotify match for '{band_name}' (top: '{items[0]['name']}')")
        return None

    return {
        "spotify_id": best["id"],
        "spotify_url": best["external_urls"]["spotify"],
        "spotify_genres": best.get("genres", []),
        "spotify_followers": best["followers"]["total"],
        "spotify_popularity": best["popularity"],
        "spotify_image_url": best["images"][0]["url"] if best.get("images") else None,
    }


def lookup_band(band_name: str, sp) -> BandResult:
    """
    Master lookup. Always returns BandResult with Google URLs populated.

    Strategy:
      1. DuckDuckGo search to find Spotify URL (more accurate for local bands)
      2. Spotify API to fetch artist data from the found URL
      3. Fall back to Spotify API direct search if DDG found nothing
      sp can be None (Spotify auth failed) — Google URLs still populated.
    """
    result = BandResult(name=band_name, **build_google_urls(band_name))

    # Step 1: Try DuckDuckGo → Spotify URL → Spotify API data
    spotify_url = find_spotify_url_via_ddg(band_name)
    if spotify_url:
        artist_id = _extract_spotify_artist_id(spotify_url)
        if artist_id and sp:
            data = get_artist_data_from_spotify(artist_id, sp)
            if data:
                result.spotify_id = data["spotify_id"]
                result.spotify_url = data["spotify_url"]
                result.spotify_genres = data["spotify_genres"]
                result.spotify_followers = data["spotify_followers"]
                result.spotify_popularity = data["spotify_popularity"]
                result.spotify_image_url = data["spotify_image_url"]
                result.lookup_status = "done"
                return result
        elif spotify_url and not sp:
            # DDG found a URL but no Spotify client — store the URL manually
            result.spotify_url = spotify_url
            result.spotify_id = artist_id
            result.lookup_status = "done"
            return result

    # Step 2: Fall back to Spotify API direct search
    if sp:
        data = lookup_spotify_direct(band_name, sp)
        if data:
            result.spotify_id = data["spotify_id"]
            result.spotify_url = data["spotify_url"]
            result.spotify_genres = data["spotify_genres"]
            result.spotify_followers = data["spotify_followers"]
            result.spotify_popularity = data["spotify_popularity"]
            result.spotify_image_url = data["spotify_image_url"]
            result.lookup_status = "done"
            return result

    if sp is None:
        result.lookup_status = "error"
        result.lookup_error = "Spotify client unavailable"
    else:
        result.lookup_status = "not_found"

    return result
