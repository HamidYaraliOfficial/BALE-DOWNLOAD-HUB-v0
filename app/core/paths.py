"""Filesystem locations (data dir, resources) – works from source and from PyInstaller."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app import APP_ID


def app_home() -> Path:
    """Per-user data directory. Override with env BDH_HOME (used by tests)."""
    env = os.environ.get("BDH_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return app_home() / "bale_download_hub.db"


def log_dir() -> Path:
    p = app_home() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_download_dir() -> Path:
    p = app_home() / "temp_downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def package_path(*parts: str) -> Path:
    """Path inside the `app` package (works in PyInstaller bundles too)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / Path(*parts)
    return Path(__file__).resolve().parents[1] / Path(*parts)


def resource_path(*parts: str) -> Path:
    return package_path("resources", *parts)
