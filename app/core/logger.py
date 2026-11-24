"""Logging with mandatory secret masking (tokens, cookies, Authorization, passwords)."""
from __future__ import annotations

import logging
import re
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)\d{5,}:[A-Za-z0-9_\-]{16,}"), "[BOT_TOKEN]"),
    (re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key)\b\s*[:=]\s*[^\r\n]+"),
     r"\1: [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?token)\b(\s*[=:]\s*)(?!\[)[^\s,;&\"']+"),
     r"\1\2[REDACTED]"),
    (re.compile(r"(?i)([?&](?:token|key|access_token|signature|sig|auth)=)[^&\s]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
]

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Register an exact secret value that must never appear in logs/reports."""
    if value and len(value) >= 6:
        with _lock:
            _secrets.add(value)


def clear_secrets() -> None:
    with _lock:
        _secrets.clear()


def mask_text(text: object) -> str:
    s = str(text)
    with _lock:
        known = list(_secrets)
    for sec in known:
        if sec in s:
            s = s.replace(sec, "[REDACTED]")
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


def mask_obj(obj):
    """Recursively mask strings inside dict/list structures."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and re.search(r"(?i)token|password|secret|cookie|authorization|api_?key", k):
                out[k] = "[REDACTED]"
            else:
                out[k] = mask_obj(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [mask_obj(v) for v in obj]
    return obj


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        record.msg = mask_text(msg)
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = mask_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class DbErrorHandler(logging.Handler):
    """Mirrors WARNING+ records into the error_logs table (already masked)."""

    def __init__(self, sink):
        super().__init__(level=logging.WARNING)
        self._sink = sink
        self._busy = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._busy, "on", False):
            return
        self._busy.on = True
        try:
            text = record.getMessage()
            if record.exc_text:
                text += "\n" + record.exc_text
            elif record.exc_info and record.exc_info[1] is not None:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
            self._sink(record.name, record.levelname, mask_text(text)[:4000])
        except Exception:
            pass
        finally:
            self._busy.on = False


_configured = False


def setup_logging(log_dir: Path, level: str = "INFO", retention_days: int = 14) -> None:
    global _configured
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if _configured:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000,
                             backupCount=max(1, retention_days // 2), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    fh.addFilter(SensitiveFilter())
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    sh.addFilter(SensitiveFilter())
    root.addHandler(sh)
    # httpx logs full request URLs at INFO – for Bale those contain the bot token.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def set_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))


def prune_old_logs(log_dir: Path, retention_days: int) -> int:
    n = 0
    cutoff = time.time() - retention_days * 86400
    for f in log_dir.glob("app.log*"):
        try:
            if f.stat().st_mtime < cutoff and f.name != "app.log":
                f.unlink()
                n += 1
        except OSError:
            pass
    return n
