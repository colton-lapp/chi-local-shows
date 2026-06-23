"""
Venue scraper registry.

Each scraper implements:
    scrape(venue_config: dict, days_ahead: int = 7) -> list[ShowResult]

The generic scraper (LLM-based) is the default for any venue not in SCRAPER_REGISTRY.
Add venue-specific scrapers here as they're built — one line per venue.
"""
from . import generic

# from . import empty_bottle  # uncomment when empty_bottle.py is ready

SCRAPER_REGISTRY: dict[str, object] = {
    # "Empty Bottle": empty_bottle.scrape,
}


def get_scraper(venue_name: str):
    """Returns venue-specific scraper if registered, else generic LLM scraper."""
    return SCRAPER_REGISTRY.get(venue_name, generic.scrape)
