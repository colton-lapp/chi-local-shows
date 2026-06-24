// Chi Local Shows — frontend JS
// Kept minimal intentionally. Add features here as the app grows.

// ── View toggle (day-grouped vs venue-grouped) ───────────────
// Not yet implemented. When ready:
//   1. Enable the #view-toggle button in _render_page() (remove `disabled`)
//   2. Add a /api/shows JSON endpoint to app.py
//   3. Implement renderByVenue() and renderByDay() here, swap on click
//
// document.getElementById('view-toggle')?.addEventListener('click', () => { ... });

// ── Future: show scoring / ranking badges ────────────────────
// Popularity score from Spotify (0–100) is already in the DB.
// Could highlight shows with headliners above a threshold.

// ── Future: map view ─────────────────────────────────────────
// Venue addresses are in the DB. Could render a Leaflet.js map
// with pins per venue, no API key required.
