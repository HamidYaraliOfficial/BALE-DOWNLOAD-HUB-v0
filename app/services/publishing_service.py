"""Publishes a processed file to one or many channels, with duplicate protection and per-channel results."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core import events
from app.core.constants import BALE_MAX_UPLOAD_BYTES
from app.core.exceptions import HubError
from app.core.logger import mask_text
from app.integrations.bale.publisher import BalePublisher
from app.services.caption import build_context, render_caption

log = logging.getLogger(__name__)
PART_SIZE = 49 * 1024 * 1024


@dataclass
class ChannelResult:
    channel_id: int | None
    label: str
    status: str                  # sent | failed | skipped_duplicate
    method: str | None = None
    message_id: int | None = None
    error: str | None = None
    error_code: str | None = None


@dataclass
class PublishOutcome:
    results: list[ChannelResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.status in ("sent", "skipped_duplicate") for r in self.results)

    @property
    def sent_count(self) -> int:
        return sum(1 for r in self.results if r.status == "sent")


def split_file(path: Path, part_size: int = PART_SIZE) -> list[Path]:
    """Alternative for files above Bale's 50 MB bot-upload limit: raw binary parts (join with `copy /b`)."""
    parts: list[Path] = []
    with open(path, "rb") as src:
        i = 1
        while True:
            chunk = src.read(part_size)
            if not chunk:
                break
            p = path.with_name(f"{path.name}.{i:03d}")
            p.write_bytes(chunk)
            parts.append(p)
            i += 1
    return parts


class PublishingService:
    def __init__(self, repo, settings_mgr, runtime, bus: events.EventBus):
        self._repo, self._sm, self._rt, self._bus = repo, settings_mgr, runtime, bus

    # ------------------------------------------------------------ routing
    def resolve_destinations(self, job: dict, category: str) -> list[dict]:
        chans = {c["id"]: c for c in self._repo.list_channels(enabled_only=True)}
        explicit = [chans[i] for i in job.get("destinations", []) if i in chans]
        if explicit:
            return explicit
        routed = [c for c in chans.values() if category in (c.get("categories") or [])]
        if routed:
            return routed
        d = self._repo.default_channel()
        return [d] if d else []

    def build_caption(self, job: dict, filename: str, size: int, category: str, info) -> str:
        if job.get("caption_override"):
            tpl = job["caption_override"]
        else:
            t = self._repo.get_template_for(category)
            tpl = t["template"] if t else self._sm.settings.publish.default_caption
        ctx = build_context(filename, size, category, job.get("url"), getattr(info, "duration", None),
                            getattr(info, "resolution", None), privacy=self._sm.settings.cleanup.privacy_mode)
        return render_caption(tpl, ctx)

    # ------------------------------------------------------------ publishing
    def publish(self, job: dict, path: str, category: str, sha256: str | None, info,
                progress=None) -> PublishOutcome:
        s = self._sm.settings
        out = PublishOutcome()
        p = Path(path)
        size = p.stat().st_size
        channels = self.resolve_destinations(job, category)
        if not channels:
            out.results.append(ChannelResult(None, "-", "failed", error="no destination channel configured",
                                             error_code="no_channel"))
            return out
        caption = self.build_caption(job, p.name, size, category, info)
        adapter = self._rt.adapter()
        pub = BalePublisher(adapter, s.publish.send_photos_as_photo, s.publish.send_videos_as_video)
        for ch in channels:
            label = ch["title"] or ch["chat_id"]
            if s.publish.duplicate_detection and sha256 and self._repo.has_fingerprint(sha256, ch["id"]):
                res = ChannelResult(ch["id"], label, "skipped_duplicate")
                self._repo.add_publish(job["id"], ch["id"], label, "skipped_duplicate", size=size,
                                       filetype=category, filename=p.name)
                out.results.append(res)
                continue
            try:
                if size > BALE_MAX_UPLOAD_BYTES and s.download.split_large_files:
                    res = self._send_split(pub, ch, p, category, caption, progress)
                else:
                    r = pub.send(ch["chat_id"], str(p), category, caption, progress)
                    res = ChannelResult(ch["id"], label, "sent", r.method, r.message_id)
                if sha256:
                    self._repo.add_fingerprint(sha256, ch["id"], size)
            except HubError as e:
                res = ChannelResult(ch["id"], label, "failed", error=mask_text(str(e))[:500],
                                    error_code=getattr(e, "code", "publish_failed"))
            except Exception as e:  # never let one channel stop the others
                log.exception("unexpected publish error")
                res = ChannelResult(ch["id"], label, "failed", error=mask_text(str(e))[:500],
                                    error_code="publish_failed")
            res.label = label
            self._repo.add_publish(job["id"], ch["id"], label, res.status, res.method, res.message_id,
                                   res.error, size, category, p.name)
            out.results.append(res)
        return out

    def _send_split(self, pub, ch, p: Path, category: str, caption: str, progress) -> ChannelResult:
        parts = split_file(p)
        last_id, method = 0, "sendDocument"
        for i, part in enumerate(parts, 1):
            cap = f"{caption}\n[{i}/{len(parts)}]".strip()
            r = pub.send(ch["chat_id"], str(part), "other", cap, progress)
            last_id, method = r.message_id, r.method + f" x{len(parts)}"
            part.unlink(missing_ok=True)
        return ChannelResult(ch["id"], ch["title"] or ch["chat_id"], "sent", method, last_id)
