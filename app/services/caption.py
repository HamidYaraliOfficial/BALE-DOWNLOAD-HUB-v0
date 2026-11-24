"""Caption Template Engine. Unknown/empty variables are removed cleanly (no '{x}' or dangling labels)."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from app.core.constants import BALE_MAX_CAPTION

VARIABLES = ["filename", "filesize", "filetype", "date", "time", "source", "duration", "resolution"]
_VAR = re.compile(r"\{(\w+)\}")


def human_size(n: int | float | None) -> str:
    if not n:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def human_duration(sec: float | None) -> str:
    if not sec:
        return ""
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_caption(template: str, ctx: dict[str, str | None], limit: int = BALE_MAX_CAPTION) -> str:
    lines_out: list[str] = []
    for line in (template or "").splitlines():
        names = _VAR.findall(line)
        values = {n: (ctx.get(n) or "") for n in names}
        if names and not any(values.values()):
            continue                                   # a line made only of missing values disappears
        text = _VAR.sub(lambda m: values.get(m.group(1), ""), line)
        text = re.sub(r"\(\s*\)|\[\s*\]|«\s*»", "", text)
        text = re.sub(r"\s*[|·•\-–:]\s*(?=[|·•\-–:]|$)", "", text)      # dangling separators
        text = re.sub(r"^\s*[|·•\-–:]\s*", "", text)                    # leading separator
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text or not names:
            lines_out.append(text)
    out = "\n".join(lines_out).strip()
    return out[:limit]


def build_context(filename: str, size: int, category: str, source_url: str | None, duration: float | None,
                  resolution: str | None, privacy: bool = False, now: datetime | None = None) -> dict[str, str]:
    now = now or datetime.now()
    host = ""
    if source_url and not privacy:
        try:
            host = urlsplit(source_url).hostname or ""
        except ValueError:
            host = ""
    return {"filename": filename, "filesize": human_size(size), "filetype": category,
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"), "source": host,
            "duration": human_duration(duration), "resolution": resolution or ""}


DEFAULT_TEMPLATES = {
    "default": ("Default", "{filename}\n{filesize}"),
    "image": ("Image", "{filename}\n{resolution} | {filesize}"),
    "video": ("Video", "{filename}\n{duration} | {resolution} | {filesize}"),
    "audio": ("Audio", "{filename}\n{duration} | {filesize}"),
    "document": ("Document", "{filename}\n{filesize}"),
}
