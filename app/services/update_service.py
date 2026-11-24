"""Update *check* only. Nothing is ever downloaded or installed without the user doing it."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app import __version__
from app.security.url_safety import validate_url


@dataclass
class UpdateInfo:
    available: bool
    current: str
    latest: str = ""
    notes: str = ""
    security: bool = False
    url: str = ""
    error: str = ""


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def check_for_updates(feed_url: str, transport: httpx.BaseTransport | None = None,
                      allow_private: bool = False) -> UpdateInfo:
    """Feed format: {"version": "1.2.0", "notes": "...", "security": false, "url": "https://..."}"""
    if not feed_url:
        return UpdateInfo(False, __version__, error="no_feed")
    try:
        validate_url(feed_url, allow_private=allow_private)
        with httpx.Client(timeout=10, transport=transport, follow_redirects=False) as c:
            r = c.get(feed_url)
            r.raise_for_status()
            d = r.json()
        latest = str(d.get("version", ""))
        return UpdateInfo(_ver(latest) > _ver(__version__), __version__, latest, str(d.get("notes", ""))[:2000],
                          bool(d.get("security")), str(d.get("url", "")))
    except Exception as e:
        return UpdateInfo(False, __version__, error=type(e).__name__)
