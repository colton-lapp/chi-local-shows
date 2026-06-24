"""
Generic venue scraper: fetch HTML → clean → LLM extraction → list[ShowResult].

Works for most venues. Always uses Playwright headless browser so JS-rendered
pages work correctly. For venues with fundamentally non-standard structures,
write a venue-specific scraper in its own file and register it in __init__.py.
"""
import json
import logging
from datetime import date, timedelta

import openai

import browser
from models import ShowResult

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000

SYSTEM_PROMPT_TEMPLATE = """\
You are a concert data extraction assistant.
Today is {today}. Extract all live band shows from this venue page that fall between {today} and {end_date} (inclusive).

Return a JSON object with a single key "shows" containing an array. Each element must have exactly these keys:
  "bands"           - array of artist/band name strings; headliner first, openers after
  "date"            - "YYYY-MM-DD" string
  "time"            - show start time like "8:00 PM" or "Doors 7PM / Show 8PM", or null
  "event_url"       - URL for this specific event page, or null
  "ticket_url"      - ticket purchase URL, or null
  "ticket_price"    - price string as shown (e.g. "$15", "$12-$15", "Free"), or null
  "age_restriction" - "21+" or "All Ages" or "18+" if stated, otherwise null
  "event_image_url" - URL of the event flyer or artwork image (look for [IMAGE:...] annotations near the event listing), or null
  "raw_title"       - original event title text as it appeared on the page
  "notes"           - any other notable detail worth surfacing: sold out, record release, special format, etc. One sentence max, or null
  "low_confidence"  - true if you are uncertain about the date, band name, or whether this qualifies as a live show; false otherwise

Rules:
  - ONLY include live music performances by bands or solo artists.
  - EXCLUDE: DJ sets, karaoke, comedy, open mic nights, trivia, private events, dance parties, film screenings.
  - If a date cannot be clearly determined, omit that event entirely.
  - Do not invent or guess data — use null for any field you cannot determine.
  - If no qualifying shows are found in the date range, return {{"shows": []}}.
{scrape_notes_section}"""

USER_PROMPT_TEMPLATE = """\
Venue: {venue_name}
Base URL (use to resolve relative links): {venue_url}

Page text:
{page_text}"""


def _fetch_and_clean(url: str) -> str:
    """Fetch a URL with Playwright and return cleaned body text."""
    if not browser.is_available():
        raise RuntimeError("Playwright not installed — run: task install")
    text = browser.fetch_html(url)
    log.debug(f"  Browser fetched {len(text)} chars from {url}")
    return text


def scrape(venue_config: dict, days_ahead: int = 7, **kwargs) -> list[ShowResult]:
    """
    Scrape all event_urls for a venue and return ShowResults for the next `days_ahead` days.
    Never raises — errors are caught, logged, and returned as ShowResults with scrape_error set.
    """
    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    results: list[ShowResult] = []
    event_urls = venue_config.get("event_urls", [])
    if not event_urls:
        return results

    scrape_notes = venue_config.get("scrape_notes", "")
    notes_section = f"\nAdditional notes for this venue:\n{scrape_notes}" if scrape_notes else ""

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        end_date=end_date.isoformat(),
        scrape_notes_section=notes_section,
    )

    client = openai.OpenAI()

    for url in event_urls:
        log.debug(f"  Fetching: {url}")

        try:
            page_text = _fetch_and_clean(url)
        except Exception as e:
            log.warning(f"  Fetch failed for {url}: {e}")
            results.append(ShowResult(
                date=today.isoformat(),
                scrape_error=f"Fetch failed: {e}",
            ))
            continue

        user_prompt = USER_PROMPT_TEMPLATE.format(
            venue_name=venue_config["name"],
            venue_url=url,
            page_text=page_text,
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)
            shows_raw = data.get("shows", [])
            if not isinstance(shows_raw, list):
                shows_raw = []
        except json.JSONDecodeError as e:
            log.error(f"  LLM returned invalid JSON for {url}: {e}")
            results.append(ShowResult(date=today.isoformat(), scrape_error=f"JSON parse error: {e}"))
            continue
        except Exception as e:
            log.error(f"  LLM call failed for {url}: {e}")
            results.append(ShowResult(date=today.isoformat(), scrape_error=f"LLM error: {e}"))
            continue

        for raw_show in shows_raw:
            show_date = raw_show.get("date")
            if not show_date:
                continue
            # Always filter dates in Python — don't rely solely on the LLM
            if not (str(today) <= show_date <= str(end_date)):
                continue

            bands = raw_show.get("bands") or []
            if not isinstance(bands, list):
                bands = [str(bands)] if bands else []

            results.append(ShowResult(
                date=show_date,
                bands=bands,
                time=raw_show.get("time"),
                event_url=raw_show.get("event_url"),
                ticket_url=raw_show.get("ticket_url"),
                ticket_price=raw_show.get("ticket_price"),
                age_restriction=raw_show.get("age_restriction"),
                event_image_url=raw_show.get("event_image_url"),
                raw_title=raw_show.get("raw_title"),
                notes=raw_show.get("notes"),
                low_confidence=bool(raw_show.get("low_confidence", False)),
            ))

        log.debug(f"  Extracted {len([r for r in results if not r.scrape_error])} shows from {url}")

    return results
