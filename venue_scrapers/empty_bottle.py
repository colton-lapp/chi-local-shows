"""
Empty Bottle venue scraper.

Currently delegates to the generic LLM scraper.
Replace with custom logic below if the generic scraper is unreliable.

The Empty Bottle (emptybottle.com) typically uses a WordPress-based events page
where each event has a date header, band name in the title, and individual event URLs.

To implement custom parsing, replace the function body with something like:

    import requests
    from bs4 import BeautifulSoup
    from datetime import date, timedelta

    def scrape(venue_config, days_ahead=7, **kwargs):
        results = []
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        for url in venue_config.get("event_urls", []):
            resp = requests.get(url, timeout=15, headers={...})
            soup = BeautifulSoup(resp.text, "lxml")
            for event in soup.select(".tribe-event"):
                date_str = event.select_one(".tribe-event-date").text.strip()
                title = event.select_one(".tribe-event-url").text.strip()
                ...
                results.append(ShowResult(date=date_str, bands=[title], ...))
        return results
"""
from models import ShowResult
from . import generic


def scrape(venue_config: dict, days_ahead: int = 7, **kwargs) -> list[ShowResult]:
    return generic.scrape(venue_config, days_ahead=days_ahead, **kwargs)
