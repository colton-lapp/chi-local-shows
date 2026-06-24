"""Show scoring — awards points across 5 criteria, max 5 points."""
import json

PREFERRED_VENUES = {"Burlington Bar", "Subterranean", "Empty Bottle"}
GUITAR_KEYWORDS = {
    "rock", "psych", "indie", "emo", "punk", "metal", "alternative",
    "garage", "shoegaze", "folk", "blues", "grunge", "country",
    "post-punk", "math rock", "noise rock", "art rock",
}
MAX_SCORE = 5
RECOMMEND_THRESHOLD = 4  # >= 80% (closest int above 75%)


def score_show(venue_name: str, bands: list) -> tuple[int, list[str]]:
    """Return (score, reasons). Score is 0–5; reasons are human-readable strings."""
    reasons: list[str] = []

    # 1. Low followers: avg < 500 across bands that have Spotify data
    follower_counts = [
        b["spotify_followers"] for b in bands if b["spotify_followers"] is not None
    ]
    if follower_counts and (sum(follower_counts) / len(follower_counts)) < 500:
        reasons.append("local/emerging band")

    # 2. Any band has a Bandcamp page
    if any(b["bandcamp_url"] for b in bands):
        reasons.append("on Bandcamp")

    # 3. Preferred venue
    if venue_name in PREFERRED_VENUES:
        reasons.append(f"great venue")

    # 4. Guitar-based genre keyword in any band's Spotify genres
    genre_text = ""
    for b in bands:
        raw = b["spotify_genres"]
        if raw:
            try:
                genre_text += " " + " ".join(json.loads(raw))
            except (ValueError, TypeError):
                pass
    if any(kw in genre_text.lower() for kw in GUITAR_KEYWORDS):
        reasons.append("guitar-based genre")

    # 5. Three or more bands on the bill
    if len(bands) > 2:
        reasons.append("multi-band lineup")

    return len(reasons), reasons


def is_recommended(score: int) -> bool:
    return score >= RECOMMEND_THRESHOLD
