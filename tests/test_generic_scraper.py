import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from venue_scrapers.generic import scrape

VENUE_CONFIG = {
    "name": "Test Venue",
    "event_urls": ["https://example.com/events"],
    "scrape_notes": "",
}

_ENOUGH_TEXT = "word " * 200  # exceeds JS_RENDER_THRESHOLD


def _llm_response(shows: list) -> MagicMock:
    m = MagicMock()
    m.choices[0].message.content = json.dumps({"shows": shows})
    return m


@pytest.fixture
def mock_fetch():
    with patch("venue_scrapers.generic.browser.fetch_html") as m:
        m.return_value = f"<html><body><p>{_ENOUGH_TEXT}</p></body></html>"
        yield m


@pytest.fixture
def mock_llm():
    with patch("venue_scrapers.generic.openai.OpenAI") as cls:
        yield cls.return_value.chat.completions.create


def test_filters_out_of_range_dates(mock_fetch, mock_llm):
    today = date.today().isoformat()
    too_far = (date.today() + timedelta(days=10)).isoformat()
    mock_llm.return_value = _llm_response([
        {"bands": ["Good Band"], "date": today, "time": "9PM", "event_url": None, "ticket_url": None, "raw_title": "Good"},
        {"bands": ["Far Band"], "date": too_far, "time": None, "event_url": None, "ticket_url": None, "raw_title": "Far"},
    ])
    results = [r for r in scrape(VENUE_CONFIG, days_ahead=7) if not r.scrape_error]
    assert len(results) == 1
    assert results[0].bands == ["Good Band"]


def test_returns_error_on_fetch_failure(mock_llm):
    with patch("venue_scrapers.generic.browser.fetch_html", side_effect=Exception("Connection refused")):
        results = scrape(VENUE_CONFIG)
    assert len(results) == 1
    assert results[0].scrape_error is not None
    assert "Fetch failed" in results[0].scrape_error


def test_returns_error_on_llm_json_failure(mock_fetch, mock_llm):
    mock_llm.return_value = MagicMock()
    mock_llm.return_value.choices[0].message.content = "not valid json {{"
    results = scrape(VENUE_CONFIG)
    assert any(r.scrape_error for r in results)


def test_handles_null_bands_field(mock_fetch, mock_llm):
    today = date.today().isoformat()
    mock_llm.return_value = _llm_response([
        {"bands": None, "date": today, "time": None, "event_url": None, "ticket_url": None, "raw_title": "Mystery"},
    ])
    results = [r for r in scrape(VENUE_CONFIG, days_ahead=7) if not r.scrape_error]
    assert len(results) == 1
    assert results[0].bands == []


def test_scrape_notes_injected_into_system_prompt(mock_llm):
    config = {**VENUE_CONFIG, "scrape_notes": "Exclude DJ nights please"}
    with patch("venue_scrapers.generic.browser.fetch_html") as m:
        m.return_value = f"<html><body>{_ENOUGH_TEXT}</body></html>"
        mock_llm.return_value = _llm_response([])
        scrape(config, days_ahead=7)

    call_kwargs = mock_llm.call_args.kwargs
    system_msg = call_kwargs["messages"][0]["content"]
    assert "Exclude DJ nights please" in system_msg


def test_empty_event_urls_returns_empty():
    config = {**VENUE_CONFIG, "event_urls": []}
    results = scrape(config)
    assert results == []


def test_multiple_bands_preserved(mock_fetch, mock_llm):
    today = date.today().isoformat()
    mock_llm.return_value = _llm_response([
        {"bands": ["Headliner", "Opener 1", "Opener 2"], "date": today,
         "time": "8PM", "event_url": None, "ticket_url": None, "raw_title": "Headliner w/ openers"},
    ])
    results = [r for r in scrape(VENUE_CONFIG, days_ahead=7) if not r.scrape_error]
    assert results[0].bands == ["Headliner", "Opener 1", "Opener 2"]
