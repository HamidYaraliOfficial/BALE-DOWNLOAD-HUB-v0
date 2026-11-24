"""Thumbnail generation for the local preview (Bale's documented send methods do not accept
custom thumbnails for sendDocument/sendVideo, so these are not uploaded)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.media.analyzer import find_tool


def image_thumbnail(src: Path, dest: Path, size: int = 320) -> Path | None:
    try:
        from PIL import Image
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, "JPEG", quality=82)
        return dest
    except Exception:
        return None


def video_thumbnail(src: Path, dest: Path, size: int = 320, at_seconds: float = 1.0) -> Path | None:
    exe = find_tool("ffmpeg")
    if not exe:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    for ts in (at_seconds, 0.0):
        r = subprocess.run([exe, "-v", "error", "-y", "-ss", str(ts), "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale={size}:-1", str(dest)], capture_output=True, timeout=60)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return dest
    return None


def make_thumbnail(src: Path, category: str, dest_dir: Path) -> Path | None:
    dest = dest_dir / f"{src.stem}.thumb.jpg"
    if category == "image":
        return image_thumbnail(src, dest)
    if category == "video":
        return video_thumbnail(src, dest)
    return None
