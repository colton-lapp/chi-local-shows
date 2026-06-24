#!/usr/bin/env python3
"""Generate static index.html for GitHub Pages deployment.

Run after fetch.py has populated the DB:
    uv run python export.py
"""
from pathlib import Path

import db
from app import _build_html

db.init_db()
html = _build_html(static_root="static")
Path("index.html").write_text(html, encoding="utf-8")
print("Wrote index.html")
