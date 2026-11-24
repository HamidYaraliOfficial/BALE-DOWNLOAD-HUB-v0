"""yt-dlp integration for publicly available media pages. Uses the Python API (no shell, no subprocess).

Limits (documented in docs/SECURITY.md):
* yt-dlp performs its own network requests, so only the *entry* URL passes through our SSRF validator.
* DRM-protected or live streams are refused; no cookies/credentials are ever supplied.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app.core.config import DownloadSettings
from app.core.exceptions import DownloadError, FileTooLarge, JobCancelled, JobPaused, NotDownloadable
from app.core.logger import mask_text
from app.downloader.types import DownloadResult, JobControl, ProbeInfo, ProgressCb
from app.downloader.validators import classify, sanitize_filename

log = logging.getLogger(__name__)
MB = 1024 * 1024


class _QuietLogger:
    """Keeps yt-dlp from writing to stderr; messages go to our (masked) debug log instead."""

    def debug(self, msg): log.debug("yt-dlp: %s", msg)
    def info(self, msg): log.debug("yt-dlp: %s", msg)
    def warning(self, msg): log.debug("yt-dlp warning: %s", msg)
    def error(self, msg): log.debug("yt-dlp error: %s", msg)


class MediaExtractor:
    def __init__(self, get_settings: Callable[[], DownloadSettings], bandwidth_getter: Callable[[], int] | None = None):
        self._gs = get_settings
        self._bw = bandwidth_getter or (lambda: 0)

    @staticmethod
    def available() -> bool:
        try:
            import yt_dlp  # noqa: F401
            return True
        except Exception:
            return False

    def _base_opts(self) -> dict:
        s = self._gs()
        return {
            "quiet": True, "no_warnings": True, "noplaylist": True, "ignoreconfig": True,
            "cachedir": False, "no_color": True, "socket_timeout": s.read_timeout_s,
            "retries": s.retry_count, "extractor_retries": 1, "allow_unplayable_formats": False,
            "geo_bypass": False, "enable_file_urls": False, "playlist_items": "1",
            "ratelimit": (self._bw() * 1024) or None, "logger": _QuietLogger(),
        }

    def probe(self, url: str) -> ProbeInfo:
        import yt_dlp
        opts = self._base_opts() | {"skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.sanitize_info(ydl.extract_info(url, download=False))
        except yt_dlp.utils.DownloadError as e:
            raise NotDownloadable(mask_text(str(e))[:300], code="media_unsupported") from None
        if info.get("is_live"):
            raise NotDownloadable("live streams are not supported", code="live_stream")
        fmts = info.get("formats") or []
        if info.get("_has_drm") or (fmts and all(f.get("has_drm") for f in fmts)):
            raise NotDownloadable("content is DRM-protected", code="drm_protected")
        title = info.get("title") or "media"
        ext = info.get("ext") or "mp4"
        size = info.get("filesize") or info.get("filesize_approx")
        name = sanitize_filename(f"{title}.{ext}", "media.mp4")
        pi = ProbeInfo(url=url, final_url=info.get("webpage_url") or url, kind="media", filename=name,
                       title=title, size=int(size) if size else None, mime=None,
                       category=classify(name), duration=info.get("duration"), resumable=True)
        return pi

    def download(self, url: str, dest_dir: Path, ctrl: JobControl, progress: ProgressCb | None = None) -> DownloadResult:
        import yt_dlp
        s = self._gs()
        max_bytes = s.max_file_size_mb * MB
        dest_dir.mkdir(parents=True, exist_ok=True)
        state: dict = {"abort": None}

        def hook(d: dict) -> None:
            try:
                ctrl.check()
                if d.get("status") == "downloading":
                    done = int(d.get("downloaded_bytes") or 0)
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    if done > max_bytes:
                        raise FileTooLarge(f"download exceeded limit of {max_bytes} bytes")
                    if progress:
                        progress(done, int(total) if total else None, float(d.get("speed") or 0.0))
            except (JobCancelled, JobPaused, FileTooLarge) as e:
                state["abort"] = e
                raise yt_dlp.utils.DownloadCancelled(str(e)) from None

        # Prefer mp4 up to 720p so the result is likely to fit Bale's 50 MB upload limit.
        opts = self._base_opts() | {
            "outtmpl": str(dest_dir / "%(title).80B [%(id)s].%(ext)s"), "windowsfilenames": True,
            "paths": {"home": str(dest_dir), "temp": str(dest_dir)},
            "format": "b[ext=mp4]/bv*[ext=mp4]+ba[ext=m4a]/b", "format_sort": ["res:720", "ext:mp4:m4a"],
            "merge_output_format": "mp4", "max_filesize": max_bytes, "progress_hooks": [hook],
            "continuedl": True, "overwrites": False, "writethumbnail": False, "writeinfojson": False,
            "writesubtitles": False, "writedescription": False,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                info = ydl.sanitize_info(info)
        except yt_dlp.utils.DownloadCancelled:
            raise state["abort"] or JobCancelled("cancelled") from None
        except yt_dlp.utils.DownloadError as e:
            if state["abort"]:
                raise state["abort"] from None
            raise DownloadError(mask_text(str(e))[:300], code="media_download_failed") from None
        if state["abort"]:
            raise state["abort"]
        reqs = info.get("requested_downloads") or []
        path = reqs[0].get("filepath") if reqs else None
        if not path or not Path(path).exists():
            files = [p for p in dest_dir.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
            if not files:
                raise DownloadError("yt-dlp produced no file", code="media_download_failed")
            path = str(max(files, key=lambda p: p.stat().st_size))
        p = Path(path)
        size = p.stat().st_size
        if size > max_bytes:
            raise FileTooLarge(f"{size} bytes exceeds limit of {max_bytes}")
        from app.downloader.direct import file_sha256
        return DownloadResult(path=str(p), size=size, sha256=file_sha256(p), filename=p.name, kind="media",
                              extra={"duration": info.get("duration"), "title": info.get("title")})
