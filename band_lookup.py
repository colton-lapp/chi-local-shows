"""
Band lookup: find a band's Spotify profile, social links, and related URLs.

Search strategy (in order):
  1. DuckDuckGo broad search: "{band}" chicago
     → classifies results into: Spotify artist URL, Instagram, Bandcamp, top-5 others
     → if Spotify URL found: fetch artist data via Spotify API
     → if no Spotify URL: targeted DDG retry for site:open.spotify.com/artist
  2. Bing via Playwright headless browser (if DDG rate-limited or returns nothing)
  3. Spotify API direct artist search (fallback, less Chicago-context-aware)

Google search URLs are always constructed as a manual fallback regardless of outcome.
"""
import logging
import re
import time
from urllib.parse import quote_plus, urlparse

import spotipy

from models import BandResult

log = logging.getLogger(__name__)

DDGS_SLEEP = 1.5

# Domains excluded from other_urls (pure search/utility noise)
_EXCLUDE_DOMAINS = {"google.com", "bing.com", "duckduckgo.com", "yahoo.com"}


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


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _ddg_search(query: str, num_results: int = 15) -> list[dict]:
    """Run a DuckDuckGo text search. Returns [] on any error."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=num_results))
    except Exception as e:
        log.debug(f"DDG search failed ({query!r}): {e}")
        return []


def _classify_results(results: list[dict]) -> dict:
    """
    Walk search result URLs and bucket into: spotify_url, instagram_url,
    bandcamp_url, and up to 5 other_urls. Stops filling each bucket once found.
    """
    found: dict = {"spotify_url": None, "instagram_url": None, "bandcamp_url": None, "other_urls": []}
    for r in results:
        url = r.get("href", "")
        if not url:
            continue
        if _extract_spotify_artist_id(url) and not found["spotify_url"]:
            found["spotify_url"] = url
        elif "instagram.com" in url and not found["instagram_url"]:
            found["instagram_url"] = url
        elif "bandcamp.com" in url and not found["bandcamp_url"]:
            found["bandcamp_url"] = url
        elif (
            len(found["other_urls"]) < 5
            and not any(d in url for d in ("spotify.com", "instagram.com", "bandcamp.com"))
            and _domain(url) not in _EXCLUDE_DOMAINS
        ):
            found["other_urls"].append(url)
    return found


def find_band_urls_via_ddg(band_name: str) -> dict:
    """
    Run a broad DDG search and extract Spotify, Instagram, Bandcamp, and other URLs.
    If no Spotify URL surfaces, retries with a targeted Spotify-specific query.
    Returns {spotify_url, instagram_url, bandcamp_url, other_urls}.
    """
    results = _ddg_search(f'"{band_name}" chicago', num_results=15)
    time.sleep(DDGS_SLEEP)
    found = _classify_results(results)

    # Targeted Spotify retry if broad search missed it
    if not found["spotify_url"]:
        sp_results = _ddg_search(f"{band_name} site:open.spotify.com/artist", num_results=5)
        time.sleep(DDGS_SLEEP)
        for r in sp_results:
            url = r.get("href", "")
            if _extract_spotify_artist_id(url):
                found["spotify_url"] = url
                break

    return found


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
    Fallback: search Spotify API directly by artist name.
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
        log.debug(f"No confident Spotify match for '{band_name}' (top result: '{items[0]['name']}')")
        return None

    return {
        "spotify_id": best["id"],
        "spotify_url": best["external_urls"]["spotify"],
        "spotify_genres": best.get("genres", []),
        "spotify_followers": best["followers"]["total"],
        "spotify_popularity": best["popularity"],
        "spotify_image_url": best["images"][0]["url"] if best.get("images") else None,
    }


def _apply_spotify_data(result: BandResult, data: dict) -> BandResult:
    result.spotify_id = data["spotify_id"]
    result.spotify_url = data["spotify_url"]
    result.spotify_genres = data["spotify_genres"]
    result.spotify_followers = data["spotify_followers"]
    result.spotify_popularity = data["spotify_popularity"]
    result.spotify_image_url = data["spotify_image_url"]
    result.lookup_status = "done"
    return result


def lookup_band(band_name: str, sp) -> BandResult:
    """
    Master lookup. Always returns BandResult with Google URLs populated.

    1. DDG broad search → Spotify URL + Instagram + Bandcamp + other URLs
    2. Browser Bing search if DDG found no Spotify URL (Playwright)
    3. Spotify API direct search as final fallback
    sp can be None (Spotify auth failed) — social links and Google URLs still populated.
    """
    result = BandResult(name=band_name, **build_google_urls(band_name))

    # Step 1: DDG → all social URLs
    ddg = find_band_urls_via_ddg(band_name)
    result.instagram_url = ddg["instagram_url"]
    result.bandcamp_url = ddg["bandcamp_url"]
    result.other_urls = ddg["other_urls"]
    spotify_url = ddg["spotify_url"]

    # Step 2: Browser Bing search if DDG found no Spotify URL
    if not spotify_url:
        try:
            import browser
            if browser.is_available():
                log.debug(f"  Trying browser search for '{band_name}'")
                spotify_url = browser.search_for_spotify_url(band_name)
        except Exception as e:
            log.debug(f"  Browser search failed for '{band_name}': {e}")

    # Fetch Spotify artist data from the found URL
    if spotify_url:
        artist_id = _extract_spotify_artist_id(spotify_url)
        if artist_id and sp:
            data = get_artist_data_from_spotify(artist_id, sp)
            if data:
                return _apply_spotify_data(result, data)
        elif not sp:
            result.spotify_url = spotify_url
            result.spotify_id = _extract_spotify_artist_id(spotify_url)
            result.lookup_status = "done"
            return result

    # Step 3: Spotify API direct search fallback
    if sp:
        data = lookup_spotify_direct(band_name, sp)
        if data:
            return _apply_spotify_data(result, data)

    # Final status
    if result.instagram_url or result.bandcamp_url or result.spotify_url:
        result.lookup_status = "done"
    elif sp is None:
        result.lookup_status = "error"
        result.lookup_error = "Spotify client unavailable"
    else:
        result.lookup_status = "not_found"

    return result
