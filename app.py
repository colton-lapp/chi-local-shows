#!/usr/bin/env python3
"""
Local web viewer for chi-local-shows.
Usage: uv run python app.py [port]   (default: 8000)
"""
import html as html_lib
import json
import mimetypes
import re
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import db

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DAYS = 7
STATIC_DIR = Path(__file__).parent / "static"

_VENUES_JSON = Path(__file__).parent / "venues.json"
_venue_cfg: dict[str, dict] = {
    v["name"]: v for v in json.loads(_VENUES_JSON.read_text())
}

_LOGO_URLS = json.loads((STATIC_DIR / "logo_urls.json").read_text())
_LOGO_SPOTIFY = f'<img src="{_LOGO_URLS["spotify"]}" class="social-icon" alt="" width="14" height="14">'
_LOGO_INSTAGRAM_ROW = f'<img src="{_LOGO_URLS["instagram"]}" class="social-row-logo-img" alt="Instagram">'
_LOGO_BANDCAMP_ROW = f'<img src="{_LOGO_URLS["bandcamp"]}" class="social-row-logo-img" alt="Bandcamp">'


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


# ── Badges ───────────────────────────────────────────────────────────────────
# key -> (emoji, label, tooltip). Thresholds are rough starting points, easy to retune.
_SHOW_BADGES = {
    "established": ("🌟", "Established Acts", "The average band on this bill has a substantial Spotify following."),
    "rising": ("🌱", "Rising Night", "This bill leans toward newer, still-emerging acts."),
    "free": ("🎟️", "Free Show", "This show appears to be free to attend."),
}
_BAND_BADGES = {
    "deep_catalog": ("📀", "Deep Catalog", "This band has released a large catalog of tracks."),
    "new": ("🆕", "New Act", "This band's first release came out in the last year."),
    "veteran": ("🕰️", "Veteran", "This band has been releasing music for 10+ years."),
    "popular": ("🔥", "Popular", "This band has a large Spotify following."),
    "underground": ("🔍", "Underground", "This band has a small/emerging Spotify following."),
}

_ESTABLISHED_AVG_FOLLOWERS = 5_000
_RISING_AVG_FOLLOWERS = 1_000
_RISING_AVG_YEARS = 2
_DEEP_CATALOG_TRACKS = 30
_NEW_ACT_YEARS = 1
_VETERAN_YEARS = 10
_POPULAR_FOLLOWERS = 50_000
_UNDERGROUND_FOLLOWERS = 500


def _years_since(release: str | None) -> float | None:
    if not release:
        return None
    try:
        return date.today().year - int(release[:4])
    except ValueError:
        return None


def _badge_html(key: str, table: dict, css_class: str) -> str:
    emoji, label, tooltip = table[key]
    return f'<span class="{css_class}" title="{_esc(tooltip)}">{emoji} {_esc(label)}</span>'


def _render_band_badges(b) -> str:
    keys = []
    if b["spotify_track_count"] and b["spotify_track_count"] > _DEEP_CATALOG_TRACKS:
        keys.append("deep_catalog")

    years = _years_since(b["spotify_first_release"])
    if years is not None:
        if years < _NEW_ACT_YEARS:
            keys.append("new")
        elif years >= _VETERAN_YEARS:
            keys.append("veteran")

    followers = b["spotify_followers"]
    if followers is not None:
        if followers > _POPULAR_FOLLOWERS:
            keys.append("popular")
        elif followers < _UNDERGROUND_FOLLOWERS:
            keys.append("underground")

    if not keys:
        return ""
    badges = "".join(_badge_html(k, _BAND_BADGES, "band-badge") for k in keys)
    return f'<div class="band-badges">{badges}</div>'


def _render_show_badges(bands, ticket_price) -> str:
    keys = []

    follower_counts = [b["spotify_followers"] for b in bands if b["spotify_followers"] is not None]
    avg_followers = sum(follower_counts) / len(follower_counts) if follower_counts else None

    year_gaps = [y for y in (_years_since(b["spotify_first_release"]) for b in bands) if y is not None]
    avg_years = sum(year_gaps) / len(year_gaps) if year_gaps else None

    if avg_followers is not None and avg_followers > _ESTABLISHED_AVG_FOLLOWERS:
        keys.append("established")
    elif (
        avg_followers is not None and avg_years is not None
        and avg_followers < _RISING_AVG_FOLLOWERS and avg_years < _RISING_AVG_YEARS
    ):
        keys.append("rising")

    if ticket_price and re.search(r"free|\$0\b", ticket_price, re.IGNORECASE):
        keys.append("free")

    return "".join(_badge_html(k, _SHOW_BADGES, "show-badge") for k in keys)


def _band_missing_note(b) -> str:
    status = b["lookup_status"]
    if status == "not_found":
        return "No Spotify profile found for this band."
    if status == "error":
        return "Spotify lookup unavailable for this band."
    if status == "done" and not b["spotify_image_url"]:
        return "Spotify match found, but no photo available."
    return ""


def _render_legend() -> str:
    items = "".join(
        f'<span class="legend-item" title="{_esc(tip)}">{emoji} {_esc(label)}</span>'
        for emoji, label, tip in {**_SHOW_BADGES, **_BAND_BADGES}.values()
    )
    return f'<section class="badge-legend"><span class="legend-label">Badges:</span>{items}</section>'


# ── Component renderers ───────────────────────────────────────────────────────

def _render_social_row(logo_html: str, label: str, url: str, title, snippet) -> str:
    """
    A two-column clickable row: platform logo | title + 2-3 line blurb.
    No card background/border — an "invisible" click target across the whole
    row (subtle hover highlight only), not a boxed card.
    """
    title_html = f'<span class="social-row-title">{_esc(title)}</span>' if title else ""
    text = _esc(snippet) if snippet else f"View on {_esc(label)}"
    return f"""<a class="social-row" href="{_esc(url)}" target="_blank">
      <span class="social-row-logo">{logo_html}</span>
      <span class="social-row-text">{title_html}<span class="social-row-snippet">{text}</span></span>
    </a>"""


def _render_social_not_found(label: str, search_url: str) -> str:
    """Fallback row when a platform link wasn't found: a button to a pre-filled
    Google search for it instead."""
    return (
        f'<a class="social-not-found" href="{_esc(search_url)}" target="_blank">'
        f'No {_esc(label)} found — search for {_esc(label)}</a>'
    )


def _render_band_card(b) -> str:
    name = _esc(b["name"])
    spotify_id = b["spotify_id"]
    spotify_url = b["spotify_url"]
    instagram_url = b["instagram_url"]
    instagram_snippet = b["instagram_snippet"]
    instagram_title = b["instagram_title"]
    bandcamp_url = b["bandcamp_url"]
    bandcamp_snippet = b["bandcamp_snippet"]
    bandcamp_title = b["bandcamp_title"]
    bandcamp_album_id = b["bandcamp_album_id"]
    google_instagram_url = b["google_instagram_url"]
    google_bandcamp_url = b["google_bandcamp_url"]
    image_url = b["spotify_image_url"]
    fallback_url = b["google_general_url"]
    popularity = b["spotify_popularity"]
    other_urls_raw = b["other_urls"]

    # ── Left column: info ────────────────────────────────────
    missing_note = _band_missing_note(b)
    if image_url:
        img_html = f'<img class="band-img" src="{_esc(image_url)}" alt="{name}" loading="lazy">'
    else:
        title_attr = f' title="{_esc(missing_note)}"' if missing_note else ""
        img_html = f'<div class="band-img-placeholder"{title_attr}>♪</div>'
    note_html = f'<div class="band-note">{_esc(missing_note)}</div>' if missing_note else ""
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

    # Instagram row, then Bandcamp row — each a 2-column (logo | title + blurb)
    # clickable row when found, or a "not found, search Google" fallback button
    # when not. Spotify is a separate plain button at the bottom (it already gets
    # a full embed on the right, so it doesn't need a row of its own).
    if instagram_url:
        instagram_row = _render_social_row(_LOGO_INSTAGRAM_ROW, "Instagram", instagram_url, instagram_title, instagram_snippet)
    elif google_instagram_url:
        instagram_row = _render_social_not_found("Instagram", google_instagram_url)
    else:
        instagram_row = ""

    if bandcamp_url:
        bandcamp_row = _render_social_row(_LOGO_BANDCAMP_ROW, "Bandcamp", bandcamp_url, bandcamp_title, bandcamp_snippet)
    elif google_bandcamp_url:
        bandcamp_row = _render_social_not_found("Bandcamp", google_bandcamp_url)
    else:
        bandcamp_row = ""

    social_rows_html = (
        f'<div class="social-rows">{instagram_row}{bandcamp_row}</div>'
        if instagram_row or bandcamp_row else ""
    )

    spotify_button_html = (
        f'<a class="btn-spotify" href="{_esc(spotify_url)}" target="_blank">'
        f'{_LOGO_SPOTIFY} Go to Spotify</a>'
        if spotify_url else ""
    )

    badges_html = _render_band_badges(b)

    info_col = f"""<div class="band-info-col">
      <div class="band-top-row">
        {img_html}
        <div class="band-top-text">
          {name_html}
          {genre_chips}
          {meta_html}
          {badges_html}
          {note_html}
        </div>
      </div>
      {social_rows_html}
      {spotify_button_html}
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


def _render_show_card(show, bands) -> str:
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
    badge_html = _render_show_badges(bands, show["ticket_price"])
    meta_row = (
        f'<div class="show-chips-row">{"".join(meta_chips)}{badge_html}</div>'
        if meta_chips or badge_html else ""
    )

    notes_html = f'<div class="show-notes">{_esc(show["notes"])}</div>' if show["notes"] else ""

    # Show main column: title (prominent) → time/date → chips + badges
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

    return (
        f'<div class="show-card" '
        f'data-date="{_esc(show_date)}" data-venue="{_esc(venue_name)}">\n'
        f'  <div class="show-header">\n'
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
        f'  <details open>\n'
        f'    <summary class="day-label">{label}</summary>\n'
        f'    {"".join(cards)}\n'
        f'  </details>\n'
        f'</section>'
    )


def _render_intro() -> str:
    return """<section class="site-intro">
    <p><strong>A Chicago local-show aggregator.</strong> This page collects upcoming show
    listings from a handful of local Chicago venues in one place &mdash; show details, Spotify
    previews of songs (when available), and links to tickets and band profiles.</p>
    <p>⚠️ <strong>This website may contain errors </strong> ⚠️ This app uses AI to read venue webpages,
    parse the results, and then search the internet for spotify/instagram/bandcamp links. Shows may be missed, incorrect bands might
    be identified, and show details can be incorrectly parsed. All show details should be confirmed on venue website.
    <a href="ai-usage.html">Learn More</a></p>
    <p>This is a hobby project, built and hosted for free on GitHub.
    <a href="https://github.com/colton-lapp/chi-local-shows" target="_blank">View the code</a> &middot;
    <a href="about.html">How this works / FAQ</a></p>
    <p>AI helped build this site, and a small AI model is used weekly to pull show listings out
    of venue websites. <a href="ai-usage.html">Read how and why &rarr;</a></p>
  </section>"""


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
            cards.append(_render_show_card(show, bands))
        sections.append(_render_day_section(label, cards, d))

    listing = (
        "".join(sections)
        if sections
        else (
            f"<p style='padding:2rem;color:#999'>No shows between "
            f"{today.strftime('%B %-d')} and {end.strftime('%B %-d, %Y')}.</p>"
        )
    )
    body = _render_intro() + _render_legend() + listing
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
