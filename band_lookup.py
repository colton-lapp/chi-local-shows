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
import difflib
import logging
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
import spotipy
from bs4 import BeautifulSoup

from models import BandResult

log = logging.getLogger(__name__)

DDGS_SLEEP = 1.0
_SCRAPE_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; chi-local-shows/1.0)"}

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


def scrape_bandcamp_album_id(bandcamp_url: str) -> str | None:
    """
    Fetch a Bandcamp artist page and return the numeric album ID of the most
    recent release, suitable for use in the EmbeddedPlayer iframe URL.
    Returns None on any failure.
    """
    try:
        # Try /music listing page first — it reliably shows all releases
        base = bandcamp_url.rstrip("/")
        for url in [base + "/music", base]:
            resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=10)
            if resp.ok:
                break
        else:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Find the first album or track link on the page
        link = soup.select_one('a[href*="/album/"], a[href*="/track/"]')
        if not link:
            return None

        item_url = urljoin(base, link["href"])
        resp2 = requests.get(item_url, headers=_SCRAPE_HEADERS, timeout=10)
        if not resp2.ok:
            return None

        # Bandcamp bakes the numeric ID into every album/track page as a large int
        match = re.search(r'"id"\s*:\s*(\d{6,})', resp2.text)
        return match.group(1) if match else None

    except Exception as e:
        log.debug(f"Bandcamp scrape failed for {bandcamp_url}: {e}")
        return None


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
        from ddgs import DDGS
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
    results = _ddg_search(f'"{band_name}" chicago', num_results=8)
    time.sleep(DDGS_SLEEP)
    found = _classify_results(results)

    # Targeted Spotify retry if broad search missed it
    if not found["spotify_url"]:
        sp_results = _ddg_search(f"{band_name} site:open.spotify.com/artist", num_results=3)
        time.sleep(DDGS_SLEEP)
        for r in sp_results:
            url = r.get("href", "")
            if _extract_spotify_artist_id(url):
                found["spotify_url"] = url
                break

    return found


# A small Chicago-area opener is essentially never internationally famous, so any
# one of {non-exact name, high follower count, foreign-market signals} is a mild
# red flag, and two or more together almost always mean we grabbed the wrong artist.
FOLLOWER_SUSPICIOUS = 20_000     # extra scrutiny above this many followers
FOLLOWER_HARD_CAP = 150_000      # no local opener has this many followers — always suspicious
_FUZZY_MATCH_MIN_RATIO = 0.97    # after normalization, only trivial (punctuation/whitespace) diffs allowed
_MATCH_ACCEPT_SCORE = 2          # minimum score in _match_score() to accept a candidate

_FOREIGN_GENRE_KEYWORDS = {
    "k-pop", "j-pop", "c-pop", "mandopop", "cantopop", "j-rock", "city pop", "anime", "vocaloid",
    "latin", "reggaeton", "regional mexican", "musica mexicana", "banda", "norteno", "corrido",
    "sertanejo", "funk carioca", "brazilian", "afrobeats", "amapiano", "bollywood", "punjabi",
    "arabic", "turkish", "french pop", "french hip hop", "german hip hop", "italian pop",
    "russian", "thai", "vietnamese", "vallenato", "bachata", "merengue", "kizomba", "flamenco",
    "chanson", "schlager",
}


def _normalize_name(name: str) -> str:
    """Lowercase, strip, remove leading 'the ' for fairer comparison."""
    name = name.lower().strip()
    if name.startswith("the "):
        name = name[4:]
    return name


def _looks_foreign(artist_name: str, genres: list[str]) -> bool:
    """True if the artist name or genres suggest a non-English/non-US origin."""
    if re.search(r"[^\x00-\x7F]", artist_name):
        return True
    genre_text = " ".join(g.lower() for g in genres)
    return any(kw in genre_text for kw in _FOREIGN_GENRE_KEYWORDS)


def _match_score(band_name: str, artist_name: str, followers: int, genres: list[str]) -> int | None:
    """
    Score a Spotify search candidate's confidence of being `band_name`.
    Returns None if the name isn't even a plausible match. Otherwise returns an
    int score — callers should reject anything below _MATCH_ACCEPT_SCORE.
    """
    a_norm, b_norm = _normalize_name(artist_name), _normalize_name(band_name)
    is_exact = a_norm == b_norm
    if not is_exact and difflib.SequenceMatcher(None, a_norm, b_norm).ratio() < _FUZZY_MATCH_MIN_RATIO:
        return None

    score = 3 if is_exact else 2

    if followers > FOLLOWER_HARD_CAP:
        score -= 4
    elif followers > FOLLOWER_SUSPICIOUS:
        score -= 1

    if _looks_foreign(artist_name, genres):
        score -= 1

    return score


def get_artist_data_from_spotify(artist_id: str, sp: spotipy.Spotify) -> dict | None:
    """Fetch artist data from Spotify API using a known artist ID."""
    try:
        artist = sp.artist(artist_id)

        # Fetch album/single release stats
        track_count = None
        first_release = None
        last_release = None
        try:
            albums_resp = sp.artist_albums(artist_id, album_type="album,single", limit=50)
            items = albums_resp.get("items", [])
            if items:
                dates = [a["release_date"] for a in items if a.get("release_date")]
                total = sum(a.get("total_tracks", 0) for a in items)
                if dates:
                    first_release = min(dates)
                    last_release = max(dates)
                if total > 0:
                    track_count = total
        except Exception as e:
            log.debug(f"Spotify album fetch failed for artist '{artist_id}': {e}")

        return {
            "_name": artist["name"],  # used for validation before storing
            "spotify_id": artist["id"],
            "spotify_url": artist["external_urls"]["spotify"],
            "spotify_genres": artist.get("genres", []),
            "spotify_followers": artist["followers"]["total"],
            "spotify_popularity": artist["popularity"],
            "spotify_image_url": artist["images"][0]["url"] if artist.get("images") else None,
            "spotify_track_count": track_count,
            "spotify_first_release": first_release,
            "spotify_last_release": last_release,
        }
    except Exception as e:
        log.debug(f"Spotify artist fetch failed for ID '{artist_id}': {e}")
        return None


def lookup_spotify_direct(band_name: str, sp: spotipy.Spotify) -> dict | None:
    """
    Fallback: search Spotify API directly by artist name.
    Scores every candidate with _match_score() and takes the best one that
    clears _MATCH_ACCEPT_SCORE; see _match_score() for what makes a match suspicious.
    """
    try:
        results = sp.search(q=f"artist:{band_name}", type="artist", limit=5)
        items = results.get("artists", {}).get("items", [])
    except Exception as e:
        log.debug(f"Spotify API search failed for '{band_name}': {e}")
        return None

    if not items:
        return None

    best, best_score = None, None
    for artist in items:
        followers = artist.get("followers", {}).get("total", 0)
        score = _match_score(band_name, artist["name"], followers, artist.get("genres", []))
        if score is not None and (best_score is None or score > best_score):
            best, best_score = artist, score

    if best is None or best_score < _MATCH_ACCEPT_SCORE:
        log.debug(f"No confident Spotify match for '{band_name}' (top: '{items[0]['name']}', score={best_score})")
        return None

    # Reuse get_artist_data_from_spotify to also capture album stats
    return get_artist_data_from_spotify(best["id"], sp)


def _apply_spotify_data(result: BandResult, data: dict) -> BandResult:
    data.pop("_name", None)
    result.spotify_id = data["spotify_id"]
    result.spotify_url = data["spotify_url"]
    result.spotify_genres = data["spotify_genres"]
    result.spotify_followers = data["spotify_followers"]
    result.spotify_popularity = data["spotify_popularity"]
    result.spotify_image_url = data["spotify_image_url"]
    result.spotify_track_count = data.get("spotify_track_count")
    result.spotify_first_release = data.get("spotify_first_release")
    result.spotify_last_release = data.get("spotify_last_release")
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

    if result.bandcamp_url:
        result.bandcamp_album_id = scrape_bandcamp_album_id(result.bandcamp_url)
        log.debug(f"  Bandcamp album ID for '{band_name}': {result.bandcamp_album_id}")

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
                fetched_name = data.get("_name", "")
                followers = data.get("spotify_followers", 0) or 0
                genres = data.get("spotify_genres", [])
                score = _match_score(band_name, fetched_name, followers, genres)
                if score is None or score < _MATCH_ACCEPT_SCORE:
                    log.debug(f"  Rejecting DDG Spotify match '{fetched_name}' (score={score}) for '{band_name}'")
                    spotify_url = None  # fall through to direct API search
                else:
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
