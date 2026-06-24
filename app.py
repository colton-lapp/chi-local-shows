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
import scoring

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DAYS = 14
STATIC_DIR = Path(__file__).parent / "static"

_VENUES_JSON = Path(__file__).parent / "venues.json"
_venue_cfg: dict[str, dict] = {
    v["name"]: v for v in json.loads(_VENUES_JSON.read_text())
}

_LOGO_URLS = json.loads((STATIC_DIR / "logo_urls.json").read_text())
_LOGO_INSTAGRAM = f'<img src="{_LOGO_URLS["instagram"]}" class="social-icon" alt="" width="14" height="14">'
_LOGO_BANDCAMP  = f'<img src="{_LOGO_URLS["bandcamp"]}"  class="social-icon" alt="" width="14" height="14">'
_LOGO_SPOTIFY   = f'<img src="{_LOGO_URLS["spotify"]}"   class="social-icon" alt="" width="14" height="14">'


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_followers(n) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M Spotify followers"
    if n >= 1_000:
        return f"{n/1_000:.1f}k Spotify followers"
    return f"{n} Spotify followers"


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
                genre_text = ", ".join(_esc(g) for g in genres[:4])
                genre_chips = (
                    f'<div class="genre-tags">'
                    f'<span class="genre-label">Genres:</span> '
                    f'<span class="genre-list">{genre_text}</span>'
                    f'</div>'
                )
        except (ValueError, TypeError):
            pass

    followers = _fmt_followers(b["spotify_followers"])
    meta_parts = []
    if followers:
        meta_parts.append(f'<span class="followers-count">{_esc(followers)}</span>')

    # Extra Spotify stats (track count + release year range)
    try:
        track_count = b["spotify_track_count"]
        first_rel = b["spotify_first_release"]
        last_rel = b["spotify_last_release"]
        stat_parts = []
        if track_count:
            stat_parts.append(f"{track_count} tracks")
        if first_rel and last_rel:
            yr1, yr2 = first_rel[:4], last_rel[:4]
            stat_parts.append(f"{yr1}–{yr2}" if yr1 != yr2 else f"since {yr1}")
        elif first_rel:
            stat_parts.append(f"since {first_rel[:4]}")
        if stat_parts:
            meta_parts.append(f'<span class="spotify-stats">{" · ".join(stat_parts)}</span>')
    except (IndexError, KeyError):
        pass

    meta_html = (
        f'<div class="band-meta">{"".join(meta_parts)}</div>'
        if meta_parts else ""
    )

    links = []
    if spotify_url:
        links.append(
            f'<a class="link-spotify" href="{_esc(spotify_url)}" target="_blank">'
            f'{_LOGO_SPOTIFY} Spotify</a>'
        )
    if instagram_url:
        links.append(
            f'<a class="link-instagram" href="{_esc(instagram_url)}" target="_blank">'
            f'{_LOGO_INSTAGRAM} Instagram</a>'
        )
    if bandcamp_url:
        links.append(
            f'<a class="link-bandcamp" href="{_esc(bandcamp_url)}" target="_blank">'
            f'{_LOGO_BANDCAMP} Bandcamp</a>'
        )
    links_html = f'<div class="band-links">{"".join(links)}</div>' if links else ""

    info_col = f"""<div class="band-info-col">
      <div class="band-top-row">
        {img_html}
        <div class="band-top-text">
          {name_html}
          {genre_chips}
          {meta_html}
        </div>
      </div>
      {links_html}
    </div>"""

    # ── Right column: embeds ─────────────────────────────────
    embeds = []
    if spotify_id:
        src = f"https://open.spotify.com/embed/artist/{_esc(spotify_id)}?utm_source=generator&theme=0"
        embeds.append(
            f'<div class="spotify-embed"><iframe src="{src}" height="80" '
            f'allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" '
            f'loading="lazy"></iframe></div>'
        )
    if bandcamp_album_id:
        src = (
            f"https://bandcamp.com/EmbeddedPlayer/album={_esc(bandcamp_album_id)}"
            f"/size=small/bgcol=ffffff/linkcol=1DA0C3/artwork=small/transparent=true/"
        )
        embeds.append(
            f'<div class="bandcamp-embed"><iframe src="{src}" height="42" '
            f'seamless loading="lazy"></iframe></div>'
        )

    embeds_col = f'<div class="band-embeds-col">{"".join(embeds)}</div>'

    return f"""<div class="band-card">
    {info_col}
    {embeds_col}
  </div>"""


def _render_show_card(show, bands, score: int = 0, reasons: list | None = None) -> str:
    venue_name = show["venue_name"]
    venue = _esc(venue_name)
    event_url = show["event_url"]
    raw_title = show["raw_title"]
    show_date = show["show_date"]

    # Venue image from venues.json
    vcfg = _venue_cfg.get(venue_name, {})
    venue_image_url = vcfg.get("image_url") or ""
    venue_homepage = (vcfg.get("event_urls") or [None])[0]

    venue_img_html = (
        f'<img class="venue-thumb" src="{_esc(venue_image_url)}" alt="{venue}" loading="lazy">'
        if venue_image_url
        else '<div class="venue-thumb-placeholder"></div>'
    )

    venue_html = f'<a href="{_esc(event_url)}" target="_blank">{venue}</a>' if event_url else venue
    venue_line = f'<div class="show-venue-line"><span class="show-venue">{venue_html}</span></div>'

    venue_btn_html = ""
    if venue_homepage:
        venue_btn_html = (
            f'<a class="venue-btn" href="{_esc(venue_homepage)}" target="_blank">Venue website ↗</a>'
        )

    title_html = f'<div class="show-title">{_esc(raw_title)}</div>' if raw_title else ""

    # Time + date stacked under show name
    time_str = show["show_time"] or ""
    try:
        date_str = date.fromisoformat(show_date).strftime("%B %-d, %Y") if show_date else ""
    except (ValueError, AttributeError):
        date_str = show_date or ""
    time_html = f'<span class="show-time">{_esc(time_str)}</span>' if time_str else ""
    date_small_html = f'<span class="show-date-small">{_esc(date_str)}</span>' if date_str else ""
    time_date_parts = [p for p in [time_html, date_small_html] if p]
    time_date_html = (
        f'<div class="show-time-date">{"".join(time_date_parts)}</div>'
        if time_date_parts else ""
    )

    meta_chips = []
    if show["ticket_price"]:
        meta_chips.append(f'<span class="show-chip">{_esc(show["ticket_price"])}</span>')
    if show["age_restriction"]:
        meta_chips.append(f'<span class="show-chip">{_esc(show["age_restriction"])}</span>')
    if show["low_confidence"]:
        meta_chips.append('<span class="show-chip show-chip--warn">⚠ verify dates</span>')
    meta_row = f'<div class="show-chips">{"".join(meta_chips)}</div>' if meta_chips else ""

    notes_html = f'<div class="show-notes">{_esc(show["notes"])}</div>' if show["notes"] else ""

    # Score badge
    badge_html = ""
    is_rec = scoring.is_recommended(score)
    if is_rec and reasons:
        reasons_text = " · ".join(reasons)
        badge_html = (
            f'<div class="score-badge">⭐ Recommended — {_esc(reasons_text)}</div>'
        )

    # Show main column: title (prominent) → time/date → chips
    show_main_col = (
        f'<div class="show-main-col">'
        f'{venue_line}'
        f'{title_html}'
        f'{time_date_html}'
        f'{meta_row}'
        f'</div>'
    )

    show_layout = (
        f'<div class="show-layout">'
        f'<div class="show-venue-col">{venue_img_html}</div>'
        f'{show_main_col}'
        f'</div>'
    )

    if bands:
        bands_html = "".join(_render_band_card(b) for b in bands)
    else:
        raw = _esc(raw_title or "Unknown show")
        bands_html = (
            f'<div class="band-card"><div class="band-info-col">'
            f'<div class="band-top-row"><div class="band-img-placeholder">♪</div>'
            f'<div class="band-top-text"><span class="band-name">{raw}</span></div></div>'
            f'</div><div class="band-embeds-col"></div></div>'
        )

    extra_class = " show-card--recommended" if is_rec else ""
    return (
        f'<div class="show-card{extra_class}" '
        f'data-date="{_esc(show_date)}" data-venue="{_esc(venue_name)}">\n'
        f'  <div class="show-header">\n'
        f'    {badge_html}\n'
        f'    {show_layout}\n'
        f'    {notes_html}\n'
        f'    {venue_btn_html}\n'
        f'  </div>\n'
        f'  <div class="bands-list">{bands_html}</div>\n'
        f'</div>'
    )


def _render_day_section(label: str, cards: list[str], date_iso: str) -> str:
    return (
        f'<section class="day-section" data-date="{_esc(date_iso)}">\n'
        f'  <div class="day-label">{label}</div>\n'
        f'  {"".join(cards)}\n'
        f'</section>'
    )


def _render_page(content: str, today: date, end_date: date, static_root: str = "/static") -> str:
    subtitle = f'{today.strftime("%B %-d")} &ndash; {end_date.strftime("%B %-d, %Y")}'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chi Local Shows</title>
  <link rel="stylesheet" href="{static_root}/style.css">
</head>
<body>
  <header>
    <div class="header-top">
      <h1>Chi Local Shows</h1>
      <span class="subtitle">{subtitle}</span>
    </div>
    <div id="filters"></div>
  </header>
  <main>{content}</main>
  <script src="{static_root}/app.js"></script>
</body>
</html>"""


# ── Page builder ──────────────────────────────────────────────────────────────

def _build_html(static_root: str = "/static") -> str:
    today = date.today()
    end = today + timedelta(days=DAYS)
    shows = db.get_shows_in_range(today.isoformat(), end.isoformat())

    by_date: dict[str, list] = {}
    for show in shows:
        by_date.setdefault(show["show_date"], []).append(show)

    sections = []
    for d, day_shows in sorted(by_date.items()):
        label = date.fromisoformat(d).strftime("%A, %B %-d")
        cards = []
        for show in day_shows:
            bands = db.get_bands_for_show(show["id"])
            score, reasons = scoring.score_show(show["venue_name"], bands)
            cards.append(_render_show_card(show, bands, score, reasons))
        sections.append(_render_day_section(label, cards, d))

    body = (
        "".join(sections)
        if sections
        else (
            f"<p style='padding:2rem;color:#999'>No shows between "
            f"{today.strftime('%B %-d')} and {end.strftime('%B %-d, %Y')}.</p>"
        )
    )
    return _render_page(body, today, end, static_root)


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
