"""Link extraction, file-name sanitising, type classification and signature (magic byte) sniffing."""
from __future__ import annotations

import csv
import mimetypes
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterable

from app.core.exceptions import SecurityError
from app.security.url_safety import normalize_url

_URL_RE = re.compile(r"https?://[^\s<>\"'\\^`{}|]+", re.IGNORECASE)
_TRAIL = ".,;:!?)]}»«،؛"
MAX_IMPORT_BYTES = 5 * 1024 * 1024

_RESERVED = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}


def extract_links(text: str) -> list[str]:
    out = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(_TRAIL)
        if u:
            out.append(u)
    return out


def dedupe_links(links: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return (unique, duplicates) keeping first-seen order. Compared on normalised form."""
    seen: set[str] = set()
    uniq, dups = [], []
    for u in links:
        try:
            key = normalize_url(u)
        except Exception:
            key = u
        if key in seen:
            dups.append(u)
        else:
            seen.add(key)
            uniq.append(u)
    return uniq, dups


def read_links_file(path: str | Path) -> list[str]:
    p = Path(path)
    if p.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("import file larger than 5 MB")
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1256", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:  # pragma: no cover
        text = raw.decode("utf-8", "ignore")
    if p.suffix.lower() == ".csv":
        links: list[str] = []
        for row in csv.reader(text.splitlines()):
            for cell in row:
                links.extend(extract_links(cell))
        return links
    return extract_links(text)


# ------------------------------------------------------------------ file names
def sanitize_filename(name: str | None, fallback: str = "file", max_len: int = 120) -> str:
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace("\\", "/").split("/")[-1]                 # drop any path component
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        name = fallback
    stem, ext = os.path.splitext(name)
    if stem.upper() in _RESERVED:
        stem = f"_{stem}"
    if len(ext) > 16:
        ext = ext[:16]
    stem = stem[: max(1, max_len - len(ext))].rstrip(". ")
    return (stem or fallback) + ext


def unique_name(directory: Path, name: str) -> str:
    cand, i = name, 1
    stem, ext = os.path.splitext(name)
    while (directory / cand).exists():
        i += 1
        cand = f"{stem} ({i}){ext}"
    return cand


def safe_join(base: Path, name: str) -> Path:
    """Join and guarantee the result stays inside `base` (path-traversal guard)."""
    base_r = base.resolve()
    target = (base_r / name).resolve()
    if base_r != target and base_r not in target.parents:
        raise SecurityError("path escapes download directory", code="path_traversal")
    return target


def filename_from_headers(content_disposition: str | None, url_path: str, mime: str | None) -> str:
    from urllib.parse import unquote
    name = ""
    if content_disposition:
        m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", content_disposition, re.I)
        if m:
            try:
                name = unquote(m.group(2).strip().strip('"'), encoding=m.group(1) or "utf-8")
            except LookupError:
                name = unquote(m.group(2).strip().strip('"'))
        else:
            m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition, re.I)
            if m:
                name = m.group(1).strip()
    if not name:
        name = unquote(url_path.rsplit("/", 1)[-1])
    name = sanitize_filename(name, "download")
    if not os.path.splitext(name)[1] and mime:
        ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ""
        if ext and ext != ".bin":
            name += ext
    return name


# ------------------------------------------------------------------ classification
_EXT = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".svg", ".ico"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts"},
    "audio": {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aac", ".wma", ".amr"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods",
                 ".odp", ".csv", ".epub", ".md", ".json", ".xml"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso"},
}


def classify(filename: str, mime: str | None = None) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    for cat, exts in _EXT.items():
        if ext in exts:
            return cat
    if mime:
        top = mime.split("/")[0].lower()
        if top in ("image", "video", "audio"):
            return top
        if mime in ("application/pdf", "text/plain", "text/csv"):
            return "document"
        if mime in ("application/zip", "application/x-rar-compressed", "application/x-7z-compressed",
                    "application/gzip", "application/x-tar"):
            return "archive"
    return "other"


# ------------------------------------------------------------------ magic bytes
_SIGS: list[tuple[bytes, int, str, str]] = [
    (b"\xff\xd8\xff", 0, "image", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image", "image/png"),
    (b"GIF87a", 0, "image", "image/gif"),
    (b"GIF89a", 0, "image", "image/gif"),
    (b"BM", 0, "image", "image/bmp"),
    (b"%PDF-", 0, "document", "application/pdf"),
    (b"PK\x03\x04", 0, "archive", "application/zip"),
    (b"PK\x05\x06", 0, "archive", "application/zip"),
    (b"Rar!\x1a\x07", 0, "archive", "application/x-rar-compressed"),
    (b"7z\xbc\xaf\x27\x1c", 0, "archive", "application/x-7z-compressed"),
    (b"\x1f\x8b", 0, "archive", "application/gzip"),
    (b"ID3", 0, "audio", "audio/mpeg"),
    (b"\xff\xfb", 0, "audio", "audio/mpeg"),
    (b"\xff\xf3", 0, "audio", "audio/mpeg"),
    (b"OggS", 0, "audio", "audio/ogg"),
    (b"fLaC", 0, "audio", "audio/flac"),
    (b"\x1a\x45\xdf\xa3", 0, "video", "video/x-matroska"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, "document", "application/msword"),
]
_EXEC_SIGS = [b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"#!"]


def sniff(path: str | Path) -> dict:
    """Inspect the real content. Returns {category, mime, is_html, is_executable}."""
    with open(path, "rb") as f:
        head = f.read(64)
    res = {"category": None, "mime": None, "is_html": False, "is_executable": False}
    if any(head.startswith(s) for s in _EXEC_SIGS):
        res["is_executable"] = True
        res["category"] = "other"
        return res
    if head[4:8] == b"ftyp":
        res.update(category="video", mime="video/mp4")
        return res
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        res.update(category="image", mime="image/webp")
        return res
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        res.update(category="audio", mime="audio/wav")
        return res
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        res.update(category="video", mime="video/x-msvideo")
        return res
    for sig, off, cat, mime in _SIGS:
        if head[off:off + len(sig)] == sig:
            res.update(category=cat, mime=mime)
            return res
    low = head.lstrip().lower()
    if low.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        res["is_html"] = True
    return res


def signature_conflict(declared_category: str, sniffed: dict) -> str | None:
    """Return a reason string if the real content contradicts what we expected (never trust extensions)."""
    if sniffed["is_executable"] and declared_category != "other":
        return "executable_disguised"
    if sniffed["is_html"] and declared_category in ("image", "video", "audio", "archive"):
        return "html_instead_of_file"
    sc = sniffed["category"]
    if sc and declared_category in ("image", "video", "audio") and sc != declared_category and \
            not (declared_category == "audio" and sc == "video"):
        return "type_mismatch"
    return None
