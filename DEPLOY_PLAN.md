# Deploy Plan: GitHub Actions + GitHub Pages

## How it works
Nightly cron job fetches fresh show data and publishes a static HTML snapshot to GitHub Pages.
Served free at `https://coltonlapp.github.io/chi-local-shows` (or similar).

## Steps

### 1. Add `export.py`
Thin script that calls `_build_html()` from `app.py` and writes `index.html`:
```python
from app import _build_html
Path("index.html").write_text(_build_html())
```

### 2. Store secrets in GitHub repo settings
- `OPENAI_API_KEY`
- `SPOTIPY_CLIENT_ID`
- `SPOTIPY_CLIENT_SECRET`

### 3. Add `.github/workflows/fetch-and-publish.yml`
```yaml
on:
  schedule:
    - cron: '0 8 * * *'   # daily at 8am UTC
  workflow_dispatch:        # manual trigger

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run playwright install chromium --with-deps
      - run: uv run python fetch.py --days 14
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SPOTIPY_CLIENT_ID: ${{ secrets.SPOTIPY_CLIENT_ID }}
          SPOTIPY_CLIENT_SECRET: ${{ secrets.SPOTIPY_CLIENT_SECRET }}
      - run: uv run python export.py
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: .
          include_files: index.html,static/**
```

### 4. Enable GitHub Pages
Repo Settings → Pages → Source: `gh-pages` branch.

## Notes
- Each CI run starts with a fresh DB (no persistence needed — 14-day window fetches fast)
- `static/` dir (CSS/JS) must be published alongside `index.html`
- Playwright install adds ~1–2 min to CI runtime; total job ~5–10 min
- `workflow_dispatch` lets you trigger a manual refresh anytime
