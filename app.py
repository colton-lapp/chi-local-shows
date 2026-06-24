#!/usr/bin/env python3
"""
Local web viewer for chi-local-shows.
Usage: uv run python app.py [port]   (default: 8000)
"""
import html as html_lib
import json
import mimetypes
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import db

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DAYS = 14
STATIC_DIR = Path(__file__).parent / "static"

_VENUES_JSON = Path(__file__).parent / "venues.json"
_venue_cfg: dict[str, dict] = {
    v["name"]: v for v in json.loads(_VENUES_JSON.read_text())
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_followers(n) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M followers"
    if n >= 1_000:
        return f"{n/1_000:.1f}k followers"
    return f"{n} followers"


def _esc(s) -> str:
    return html_lib.escape(str(s)) if s else ""


# ── Component renderers ───────────────────────────────────────────────────────

def _render_band_card(b) -> str:
    name = _esc(b["name"])
    spotify_id = b["spotify_id"]
    spotify_url = b["spotify_url"]
    instagram_url = b["instagram_url"]
    bandcamp_url = b["bandcamp_url"]
    bandcamp_album_id = b["bandcamp_album_id"]
    image_url = b["spotify_image_url"]
    fallback_url = b["google_general_url"]
    popularity = b["spotify_popularity"]
    other_urls_raw = b["other_urls"]

    # ── Left column: info ────────────────────────────────────
    img_html = (
        f'<img class="band-img" src="{_esc(image_url)}" alt="{name}" loading="lazy">'
        if image_url else '<div class="band-img-placeholder">♪</div>'
    )
    primary_url = spotify_url or fallback_url
    name_html = (
        f'<a class="band-name" href="{_esc(primary_url)}" target="_blank">{name}</a>'
        if primary_url else f'<span class="band-name">{name}</span>'
    )

    genre_chips = ""
    genres_raw = b["spotify_genres"]
    if genres_raw:
        try:
            genres = json.loads(genres_raw)
            if genres:
                chips = "".join(f'<span class="genre-tag">{_esc(g)}</span>' for g in genres[:4])
                genre_chips = f'<div class="genre-tags">{chips}</div>'
        except (ValueError, TypeError):
            pass

    followers = _fmt_followers(b["spotify_followers"])
    meta_html = f'<div class="band-meta">{_esc(followers)}</div>' if followers else ""

    links = []
    if spotify_url:
        links.append(f'<a href="{_esc(spotify_url)}" target="_blank">Spotify</a>')
    if instagram_url:
        links.append(f'<a href="{_esc(instagram_url)}" target="_blank">Instagram</a>')
    if bandcamp_url:
        links.append(f'<a href="{_esc(bandcamp_url)}" target="_blank">Bandcamp</a>')
    links_html = f'<div class="band-links">{"".join(links)}</div>' if links else ""

    info_col = f"""<div class="band-info-col">
      <div class="band-top-row">
        {img_html}
        <span>{name_html}</span>
      </div>
      {genre_chips}
      {meta_html}
      {links_html}
    </div>"""

    # ── Right column: embeds ─────────────────────────────────
    embeds = []
    if spotify_id:
        src = f"https://open.spotify.com/embed/artist/{_esc(spotify_id)}?utm_source=generator&theme=0"
        embeds.append(f'<div class="spotify-embed"><iframe src="{src}" height="80" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe></div>')
    if bandcamp_album_id:
        src = f"https://bandcamp.com/EmbeddedPlayer/album={_esc(bandcamp_album_id)}/size=small/bgcol=ffffff/linkcol=2d6a4f/artwork=small/transparent=true/"
        embeds.append(f'<div class="bandcamp-embed"><iframe src="{src}" height="42" seamless loading="lazy"></iframe></div>')

    embeds_col = f'<div class="band-embeds-col">{"".join(embeds)}</div>'

    # ── More info expand ─────────────────────────────────────
    more_items = []
    if popularity is not None:
        more_items.append(f'<span>Spotify popularity: {popularity}/100</span>')
    if other_urls_raw:
        try:
            for url in json.loads(other_urls_raw)[:3]:
                more_items.append(f'<a href="{_esc(url)}" target="_blank">{_esc(url)}</a>')
        except (ValueError, TypeError):
            pass

    more_html = ""
    if more_items:
        items_html = "".join(f"<div>{item}</div>" for item in more_items)
        more_html = f'<details class="band-more"><summary>More info</summary><div class="band-more-content">{items_html}</div></details>'

    return f"""<div class="band-card">
    {info_col}
    {embeds_col}
    {more_html}
  </div>"""


def _render_show_card(show, bands) -> str:
    venue_name = show["venue_name"]
    venue = _esc(venue_name)
    event_url = show["event_url"]
    raw_title = show["raw_title"]

    # Venue image from venues.json
    vcfg = _venue_cfg.get(venue_name, {})
    venue_image_url = vcfg.get("image_url") or ""
    venue_homepage = (vcfg.get("event_urls") or [None])[0]

    venue_img_html = (
        f'<img class="venue-thumb" src="{_esc(venue_image_url)}" alt="{venue}" loading="lazy">'
        if venue_image_url
        else '<div class="venue-thumb-placeholder"></div>'
    )

    # Venue name: linked to specific show event page if available
    venue_html = f'<a href="{_esc(event_url)}" target="_blank">{venue}</a>' if event_url else venue
    time_html = f'<span class="show-time">{_esc(show["show_time"])}</span>' if show["show_time"] else ""
    venue_row = f'<div class="show-header-main">{venue_img_html}<span class="show-venue">{venue_html}</span>{time_html}</div>'

    # "Go to venue" button
    venue_btn_html = ""
    if venue_homepage:
        venue_btn_html = f'<a class="venue-btn" href="{_esc(venue_homepage)}" target="_blank">Venue website ↗</a>'

    # Show title is secondary context below the venue
    title_html = f'<div class="show-title">{_esc(raw_title)}</div>' if raw_title else ""

    # Metadata chips: ticket price, age restriction
    meta_chips = []
    if show["ticket_price"]:
        meta_chips.append(f'<span class="show-chip">{_esc(show["ticket_price"])}</span>')
    if show["age_restriction"]:
        meta_chips.append(f'<span class="show-chip">{_esc(show["age_restriction"])}</span>')
    if show["low_confidence"]:
        meta_chips.append('<span class="show-chip show-chip--warn">⚠ verify dates</span>')
    meta_row = f'<div class="show-chips">{"".join(meta_chips)}</div>' if meta_chips else ""

    # LLM notes
    notes_html = f'<div class="show-notes">{_esc(show["notes"])}</div>' if show["notes"] else ""

    if bands:
        bands_html = "".join(_render_band_card(b) for b in bands)
    else:
        raw = _esc(raw_title or "Unknown show")
        bands_html = f'<div class="band-card"><div class="band-info-col"><div class="band-top-row"><div class="band-img-placeholder">♪</div><span class="band-name">{raw}</span></div></div><div class="band-embeds-col"></div></div>'

    return f"""<div class="show-card">
  <div class="show-header">
    {venue_row}
    {venue_btn_html}
    {title_html}
    {meta_row}
    {notes_html}
  </div>
  <div class="bands-list">{bands_html}</div>
</div>"""


def _render_day_section(label: str, cards: list[str]) -> str:
    return f"""<section class="day-section">
  <div class="day-label">{label}</div>
  {"".join(cards)}
</section>"""


def _render_page(content: str, today: date) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chi Local Shows</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>Chi Local Shows</h1>
    <span class="subtitle">Next {DAYS} days &mdash; {today.strftime("%B %-d, %Y")}</span>
    <button id="view-toggle" disabled title="Coming soon">By Venue</button>
  </header>
  <main>{content}</main>
  <script src="/static/app.js"></script>
</body>
</html>"""


# ── Page builder ──────────────────────────────────────────────────────────────

def _build_html() -> str:
    today = date.today()
    end = today + timedelta(days=DAYS)
    shows = db.get_shows_in_range(today.isoformat(), end.isoformat())

    by_date: dict[str, list] = {}
    for show in shows:
        by_date.setdefault(show["show_date"], []).append(show)

    sections = []
    for d, day_shows in sorted(by_date.items()):
        label = date.fromisoformat(d).strftime("%A, %B %-d")
        cards = [
            _render_show_card(show, db.get_bands_for_show(show["id"]))
            for show in day_shows
        ]
        sections.append(_render_day_section(label, cards))

    body = "".join(sections) if sections else "<p style='padding:2rem;color:#999'>No shows in the next 14 days.</p>"
    return _render_page(body, today)


# ── HTTP handler ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/static/"):
            self._serve_static()
        else:
            self._serve_page()

    def _serve_page(self):
        html = _build_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _serve_static(self):
        rel = self.path[len("/static/"):]
        path = STATIC_DIR / rel
        if not path.is_file() or not path.resolve().is_relative_to(STATIC_DIR.resolve()):
            self.send_response(404)
            self.end_headers()
            return
        data = path.read_bytes()
        mime, _ = mimetypes.guess_type(str(path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    db.init_db()
    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    print(f"Serving at http://127.0.0.1:{PORT}")
    server.serve_forever()
