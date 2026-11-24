"""Extracts media metadata (Pillow for images, ffprobe for audio/video, zipfile for archives)."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from math import gcd
from pathlib import Path

log = logging.getLogger(__name__)


def find_tool(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    for cand in (base / "bin" / exe, base / "ffmpeg" / exe, Path(sys.executable).parent / exe):
        if cand.exists():
            return str(cand)
    return shutil.which(name)


@dataclass
class ArchiveInfo:
    entries: int = 0
    uncompressed: int = 0
    compressed: int = 0
    unsafe_paths: list[str] = field(default_factory=list)
    suspicious_ratio: bool = False


@dataclass
class MediaInfo:
    category: str
    size: int
    extension: str
    mime: str | None = None
    format: str | None = None
    width: int | None = None
    height: int | None = None
    aspect: str | None = None
    duration: float | None = None
    fps: float | None = None
    codec: str | None = None
    bitrate: int | None = None
    archive: ArchiveInfo | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def resolution(self) -> str | None:
        return f"{self.width}x{self.height}" if self.width and self.height else None


def _aspect(w: int, h: int) -> str:
    g = gcd(w, h) or 1
    a, b = w // g, h // g
    return f"{a}:{b}" if max(a, b) <= 32 else f"{w / h:.2f}:1"


def inspect_zip(path: str | Path, max_ratio: float = 200.0, max_total: int = 4 * 1024 ** 3) -> ArchiveInfo:
    """Zip-Slip / zip-bomb screening. We never extract; this only reads the central directory."""
    info = ArchiveInfo()
    with zipfile.ZipFile(path) as z:
        for zi in z.infolist():
            info.entries += 1
            info.uncompressed += zi.file_size
            info.compressed += zi.compress_size
            n = zi.filename.replace("\\", "/")
            parts = [p for p in n.split("/") if p]
            if n.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", n) or "\x00" in n:
                info.unsafe_paths.append(n[:200])
    if info.uncompressed > max_total or (info.compressed and info.uncompressed / info.compressed > max_ratio
                                         and info.uncompressed > 50 * 1024 * 1024):
        info.suspicious_ratio = True
    return info


def analyze(path: str | Path, category: str) -> MediaInfo:
    p = Path(path)
    size = p.stat().st_size
    mi = MediaInfo(category=category, size=size, extension=p.suffix.lower(),
                   mime=mimetypes.guess_type(p.name)[0])
    try:
        if category == "image":
            _image(p, mi)
        elif category in ("video", "audio"):
            _ffprobe(p, mi)
        elif category == "archive" and zipfile.is_zipfile(p):
            mi.archive = inspect_zip(p)
    except Exception as e:  # metadata is best-effort and must never abort a job
        mi.notes.append(f"metadata unavailable: {type(e).__name__}")
        log.debug("analyze failed", exc_info=True)
    return mi


def _image(p: Path, mi: MediaInfo) -> None:
    from PIL import Image
    with Image.open(p) as im:
        im.verify()
    with Image.open(p) as im:
        mi.format, (mi.width, mi.height) = im.format, im.size
    if mi.width and mi.height:
        mi.aspect = _aspect(mi.width, mi.height)


def _ffprobe(p: Path, mi: MediaInfo) -> None:
    exe = find_tool("ffprobe")
    if not exe:
        mi.notes.append("ffprobe not found – video/audio details unavailable")
        return
    r = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-i", str(p)],
                       capture_output=True, text=True, timeout=45)
    if r.returncode != 0:
        mi.notes.append("ffprobe could not read the file")
        return
    data = json.loads(r.stdout or "{}")
    fmt = data.get("format", {})
    mi.format = (fmt.get("format_name") or "").split(",")[0] or None
    mi.duration = float(fmt["duration"]) if fmt.get("duration") else None
    mi.bitrate = int(fmt["bit_rate"]) if fmt.get("bit_rate") else None
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and mi.width is None:
            mi.width, mi.height, mi.codec = st.get("width"), st.get("height"), st.get("codec_name")
            fr = st.get("avg_frame_rate", "0/1")
            try:
                n, d = fr.split("/")
                mi.fps = round(float(n) / float(d), 2) if float(d) else None
            except (ValueError, ZeroDivisionError):
                pass
            if mi.width and mi.height:
                mi.aspect = _aspect(mi.width, mi.height)
        elif st.get("codec_type") == "audio" and mi.codec is None:
            mi.codec = st.get("codec_name")
