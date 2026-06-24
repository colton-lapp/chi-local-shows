from dataclasses import dataclass, field


@dataclass
class ShowResult:
    """Returned by any venue scraper. Only date is required."""
    date: str                       # YYYY-MM-DD
    bands: list[str] = field(default_factory=list)  # headliner first, openers after
    time: str | None = None
    event_url: str | None = None
    ticket_url: str | None = None
    ticket_price: str | None = None
    age_restriction: str | None = None
    event_image_url: str | None = None
    raw_title: str | None = None
    notes: str | None = None
    low_confidence: bool = False
    scrape_error: str | None = None  # set if this result represents a partial/failed scrape


@dataclass
class BandResult:
    """Returned by band_lookup.lookup_band(). Google URLs are always populated."""
    name: str
    # Spotify fields — None if not found
    spotify_id: str | None = None
    spotify_url: str | None = None
    spotify_genres: list[str] = field(default_factory=list)
    spotify_followers: int | None = None
    spotify_popularity: int | None = None
    spotify_image_url: str | None = None
    # Social/streaming URLs found via search — None if not found
    bandcamp_url: str | None = None
    bandcamp_album_id: str | None = None  # numeric album ID for embed iframe
    instagram_url: str | None = None
    other_urls: list[str] = field(default_factory=list)  # top 5 other search result URLs
    # Google search URLs — always constructed, even on lookup failure
    google_general_url: str = ""
    google_spotify_url: str = ""
    google_bandcamp_url: str = ""
    google_instagram_url: str = ""
    # Extra Spotify stats (fetched from artist_albums)
    spotify_track_count: int | None = None
    spotify_first_release: str | None = None   # YYYY or YYYY-MM-DD
    spotify_last_release: str | None = None    # YYYY or YYYY-MM-DD
    # Lookup outcome
    lookup_status: str = "pending"   # pending | done | not_found | error
    lookup_error: str | None = None
