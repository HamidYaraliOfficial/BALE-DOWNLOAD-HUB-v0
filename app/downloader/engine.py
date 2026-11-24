"""DownloadEngine – picks the best method (direct HTTP vs yt-dlp) for a URL."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import httpx

from app.core.config import DownloadSettings
from app.core.exceptions import NotDownloadable
from app.downloader.direct import DirectDownloader, HttpFetcher
from app.downloader.media_extractor import MediaExtractor
from app.downloader.types import DownloadResult, JobControl, ProbeInfo, ProgressCb
from app.security.url_safety import Resolver, validate_url

log = logging.getLogger(__name__)
MB = 1024 * 1024


class DownloadEngine:
    def __init__(self, get_settings: Callable[[], DownloadSettings], resolver: Resolver | None = None,
                 transport: httpx.BaseTransport | None = None, allow_private: bool = False,
                 proxy: str | None = None, extractor: MediaExtractor | None = None):
        self._gs = get_settings
        self._resolver, self._allow_private = resolver, allow_private
        self.fetcher = HttpFetcher(get_settings, resolver, transport, allow_private, proxy)
        self.direct = DirectDownloader(self.fetcher, get_settings)
        self.extractor = extractor or MediaExtractor(get_settings, lambda: self._gs().bandwidth_limit_kbps)

    def close(self) -> None:
        self.fetcher.close()

    def probe(self, url: str) -> ProbeInfo:
        """Everything the user needs to confirm a download. Never raises for 'unsupported' content –
        those come back with supported=False and a machine-readable reason_code."""
        s = self._gs()
        validate_url(url, self._resolver, self._allow_private)          # raises UrlBlockedError
        info = self.fetcher.probe(url)
        if getattr(info, "_is_html", False):
            if s.use_ytdlp and self.extractor.available():
                try:
                    info = self.extractor.probe(url)
                except NotDownloadable as e:
                    return self._unsupported(info, e.code, str(e))
                except Exception as e:  # yt-dlp internal failure
                    log.info("yt-dlp probe failed: %s", e)
                    return self._unsupported(info, "html_page_not_media", "page is not a downloadable file")
            else:
                return self._unsupported(info, "html_page_not_media", "page is not a downloadable file")
        return self._apply_limits(info, s)

    @staticmethod
    def _unsupported(info: ProbeInfo, code: str, msg: str) -> ProbeInfo:
        info.supported, info.reason_code, info.reason = False, code, msg
        return info

    @staticmethod
    def _apply_limits(info: ProbeInfo, s: DownloadSettings) -> ProbeInfo:
        if info.size and info.size > s.max_file_size_mb * MB:
            return DownloadEngine._unsupported(info, "file_too_large",
                                               f"{info.size} bytes > limit {s.max_file_size_mb} MB")
        if info.category not in s.allowed_types:
            return DownloadEngine._unsupported(info, "type_not_allowed", f"file type '{info.category}' not allowed")
        return info

    def download(self, url: str, dest_dir: Path, probe: ProbeInfo, ctrl: JobControl,
                 progress: ProgressCb | None = None) -> DownloadResult:
        if probe.kind == "media":
            return self.extractor.download(url, dest_dir, ctrl, progress)
        return self.direct.download(url, dest_dir, probe, ctrl, progress)
