"""JSON based localisation (fa / en / zh). Missing keys fall back to English, then to the key."""
from __future__ import annotations

import json
import logging
import threading

from app.core.paths import package_path

log = logging.getLogger(__name__)
RTL_LANGS = {"fa"}
LANG_NAMES = {"fa": "فارسی", "en": "English", "zh": "中文"}


class Translator:
    def __init__(self, language: str = "fa"):
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        self.language = language
        self.missing: set[str] = set()      # keys requested but absent from en.json (used by UI tests)
        for lang in LANG_NAMES:
            self._load(lang)

    def _load(self, lang: str) -> None:
        p = package_path("localization", f"{lang}.json")
        try:
            self._data[lang] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.error("cannot load translation %s", p)
            self._data[lang] = {}

    def set_language(self, lang: str) -> None:
        if lang in self._data:
            self.language = lang

    @property
    def is_rtl(self) -> bool:
        return self.language in RTL_LANGS

    def has(self, key: str, lang: str | None = None) -> bool:
        return key in self._data.get(lang or self.language, {})

    def keys(self, lang: str) -> set[str]:
        return set(self._data.get(lang, {}))

    def __call__(self, key: str, **kw) -> str:
        text = self._data.get(self.language, {}).get(key)
        if text is None:
            text = self._data.get("en", {}).get(key)
            if text is None:
                self.missing.add(key)
                text = key
        if kw:
            try:
                return text.format(**kw)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def tr_in(self, lang: str, key: str, **kw) -> str:
        old = self.language
        try:
            self.language = lang if lang in self._data else old
            return self(key, **kw)
        finally:
            self.language = old
