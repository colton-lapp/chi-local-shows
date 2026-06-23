"""
Headless Chromium utilities via Playwright.

Used for:
- Venue pages that are JS-rendered (React/Vue/etc.) and return empty content with requests
- More reliable web searches when duckduckgo-search library hits rate limits

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


def search_for_spotify_url(band_name: str) -> str | None:
    """
    Use headless Chromium to search for a band's Spotify artist page.
    Returns the Spotify artist URL if found, else None.

    More reliable than DuckDuckGo library when rate-limited.
    Uses Bing (less bot-hostile than Google for automated search).
    """
    from urllib.parse import quote_plus
    from playwright.sync_api import sync_playwright
    import re

    query = f'"{band_name}" site:open.spotify.com/artist chicago'
    search_url = f"https://www.bing.com/search?q={quote_plus(query)}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            # Extract all href attributes and look for Spotify artist URLs
            links = page.eval_on_selector_all(
                "a[href*='open.spotify.com/artist']",
                "els => els.map(e => e.href)",
            )
        finally:
            browser.close()

    for link in links:
        match = re.search(r"open\.spotify\.com/artist/[A-Za-z0-9]+", link)
        if match:
            return f"https://{match.group(0)}"

    return None
