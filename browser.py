"""
Headless Chromium utilities via Playwright.

Used for:
- Venue pages that are JS-rendered (React/Vue/etc.) and return empty content with requests
- A broad Bing search (Spotify/Instagram/Bandcamp) — more bot-tolerant than scraping
  Google directly, and more reliable than the duckduckgo-search library, which is
  prone to rate limits under repeated automated queries

Playwright must be installed: `task install` (or `uv run playwright install chromium`)
"""
import logging
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000
TIMEOUT_MS = 15_000


def is_available() -> bool:
    """Return True if Playwright is installed and usable."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()
    # Preserve image URLs as inline annotations so the LLM can associate
    # event flyer/artwork images with the correct show entries.
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src.startswith("http"):
            img.replace_with(f" [IMAGE:{src}] ")
        else:
            img.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:MAX_TEXT_CHARS]


def fetch_html(url: str) -> str:
    """
    Fetch a URL with headless Chromium. Returns cleaned page text.
    Waits for network to go idle so JS-rendered content is present.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
            html = page.content()
        finally:
            browser.close()

    return _clean_html(html)


def _bing_search_links(query: str) -> list[str]:
    """Run a Bing search via headless Chromium and return every result link href."""
    from urllib.parse import quote_plus
    from playwright.sync_api import sync_playwright

    search_url = f"https://www.bing.com/search?q={quote_plus(query)}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        finally:
            browser.close()

    return links


def search_bing_urls(band_name: str) -> dict:
    """
    Use headless Chromium to run a broad Bing search and extract Spotify,
    Instagram, Bandcamp, and other URLs, same classification as the Google/DDG
    search tiers. If no Spotify URL surfaces, retries with a targeted query.
    Returns {spotify_url, instagram_url, bandcamp_url, other_urls}.

    Uses Bing (less bot-hostile than Google for automated search) and is more
    reliable than the duckduckgo-search library when it's rate-limited.
    """
    from band_lookup import _classify_results, _extract_spotify_artist_id

    links = _bing_search_links(f'"{band_name}" chicago band')
    found = _classify_results([{"href": link} for link in links])

    if not found["spotify_url"]:
        sp_links = _bing_search_links(f'"{band_name}" site:open.spotify.com/artist chicago')
        for link in sp_links:
            if _extract_spotify_artist_id(link):
                found["spotify_url"] = link
                break

    return found
