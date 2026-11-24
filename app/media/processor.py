"""Media Processing Pipeline: signature checks, optional rename / convert / thumbnail.
All content-changing steps are opt-in via settings; the original is kept until a step succeeds."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import DownloadSettings, MediaSettings
from app.core.exceptions import HubError, NotDownloadable
from app.downloader.validators import classify, safe_join, sanitize_filename, signature_conflict, sniff, unique_name
from app.media.analyzer import MediaInfo, analyze
from app.media.thumbnails import make_thumbnail
from app.security.scanner import ScanResult, scan_file

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    path: str
    info: MediaInfo
    category: str
    derived: list[str] = field(default_factory=list)
    scan: ScanResult | None = None
    thumbnail: str | None = None
    notes: list[str] = field(default_factory=list)


class MediaProcessor:
    def __init__(self, get_download_settings, get_media_settings):
        self._dl, self._md = get_download_settings, get_media_settings

    def process(self, path: str, declared_category: str, source: str = "") -> ProcessResult:
        dl: DownloadSettings = self._dl()
        md: MediaSettings = self._md()
        p = Path(path)
        notes: list[str] = []
        category = declared_category

        # 1. never trust the extension – look at the real bytes
        sn = sniff(p)
        if dl.block_executables and sn["is_executable"]:
            raise NotDownloadable("file is an executable program", code="executable_blocked")
        if dl.verify_signature:
            reason = signature_conflict(declared_category, sn)
            if reason:
                raise NotDownloadable(f"content does not match declared type ({reason})", code=reason)
            if sn["category"] and sn["category"] != category and category == "other":
                category = sn["category"]
                notes.append(f"type corrected from signature: {category}")
        if category not in dl.allowed_types:
            raise NotDownloadable(f"file type '{category}' is not allowed", code="type_not_allowed")

        # 2. metadata
        info = analyze(p, category)
        if info.archive and dl.block_unsafe_archives and info.archive.unsafe_paths:
            raise NotDownloadable("archive contains path-traversal entries (Zip Slip)", code="unsafe_archive")
        if info.archive and info.archive.suspicious_ratio and dl.block_unsafe_archives:
            raise NotDownloadable("archive looks like a decompression bomb", code="unsafe_archive")

        # 3. optional antivirus (only when enabled; absence of an engine is reported, not hidden)
        scan = None
        if md.scan_with_defender:
            scan = scan_file(str(p))
            if scan.status == "infected":
                raise NotDownloadable(f"antivirus flagged the file ({scan.engine})", code="malware_detected")
            if scan.status == "unavailable":
                notes.append("antivirus scan requested but no engine is installed")

        derived: list[str] = []
        # 4. optional image conversion (original is kept until the new file is written)
        if md.convert_images_to and category == "image":
            conv = self._convert_image(p, md.convert_images_to)
            if conv:
                if not md.keep_original_until_done or True:
                    derived_orig = p
                    p = conv
                    try:
                        derived_orig.unlink()
                    except OSError:
                        derived.append(str(derived_orig))
                info = analyze(p, category)

        # 5. optional renaming
        new_name = self._build_name(p.name, md)
        if new_name != p.name:
            target = safe_join(p.parent, unique_name(p.parent, new_name))
            os.replace(p, target)
            p = target

        # 6. optional category folder (inside the job's own temp dir)
        if md.categorize_folders:
            sub = p.parent / category
            sub.mkdir(exist_ok=True)
            target = safe_join(sub, unique_name(sub, p.name))
            os.replace(p, target)
            p = target

        thumb = None
        if md.make_thumbnails:
            t = make_thumbnail(p, category, p.parent / ".thumbs")
            thumb = str(t) if t else None
            if t:
                derived.append(str(t))
        return ProcessResult(path=str(p), info=info, category=category, derived=derived, scan=scan,
                             thumbnail=thumb, notes=notes)

    @staticmethod
    def _build_name(name: str, md: MediaSettings) -> str:
        stem, ext = os.path.splitext(name)
        new = f"{md.name_prefix}{stem}{md.name_suffix}"
        if md.rename_pattern:
            new = md.rename_pattern.replace("{name}", stem).replace("{prefix}", md.name_prefix) \
                                   .replace("{suffix}", md.name_suffix)
        if md.sanitize_names:
            return sanitize_filename(new + ext)
        return new + ext

    @staticmethod
    def _convert_image(p: Path, fmt: str) -> Path | None:
        fmt = fmt.lower().lstrip(".")
        pil = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(fmt)
        if not pil or p.suffix.lower().lstrip(".") in (fmt, "jpeg" if fmt == "jpg" else fmt):
            return None
        try:
            from PIL import Image
            target = p.with_suffix("." + ("jpg" if fmt == "jpeg" else fmt))
            with Image.open(p) as im:
                im = im.convert("RGB") if pil == "JPEG" else im
                im.save(target, pil)
            return target
        except Exception:
            log.warning("image conversion failed; keeping original", exc_info=True)
            return None
