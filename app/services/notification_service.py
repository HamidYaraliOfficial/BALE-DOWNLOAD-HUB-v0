"""In-app notifications + optional Bale messages to Super Admins/Admins for selected events."""
from __future__ import annotations

import logging
import time

from app.core import events
from app.core.logger import mask_text

log = logging.getLogger(__name__)
UI_TOAST = "ui.toast"
ERROR_EVENTS = {events.CONNECTION_ERROR, events.DOWNLOAD_ERROR, events.UPLOAD_ERROR, events.DISK_LOW,
                events.BOT_DISCONNECTED, events.QUOTA_NEAR}


class NotificationService:
    def __init__(self, repo, settings_mgr, runtime, bus: events.EventBus, tr):
        self._repo, self._sm, self._rt, self._bus, self._tr = repo, settings_mgr, runtime, bus, tr
        self._last_bale: dict[str, float] = {}
        self.history: list[dict] = []
        for e in events.NOTIFICATION_EVENTS:
            bus.subscribe(e, self._on_event)

    def _message(self, evt: str, p: dict) -> tuple[str, str]:
        key = evt.replace("notify.", "")
        name = p.get("name") or p.get("job_id", "")[:8] if p.get("job_id") else ""
        detail = mask_text(p.get("detail") or p.get("code") or "")
        try:
            freed = f"{(p.get('freed') or 0) / 1048576:.1f} MB"
        except Exception:
            freed = ""
        return (self._tr(f"notify.{key}.title"),
                self._tr(f"notify.{key}.body", name=name, detail=detail, freed=freed,
                         free=f"{(p.get('free') or 0) / 1048576:.0f} MB"))

    def _on_event(self, evt: str, **p) -> None:
        s = self._sm.settings.notifications
        if s.in_app.get(evt, True):
            title, body = self._message(evt, p)
            item = {"event": evt, "title": title, "body": body, "error": evt in ERROR_EVENTS, "ts": time.time()}
            self.history.append(item)
            del self.history[:-200]
            self._bus.publish(UI_TOAST, title=item["title"], body=item["body"], error=item["error"], ts=item["ts"])
        if s.notify_admins_on_bale and evt in s.bale_events and evt != events.BOT_DISCONNECTED \
                and evt != events.CONNECTION_ERROR:
            self._to_admins(evt, p)

    def _to_admins(self, evt: str, p: dict) -> None:
        now = time.monotonic()
        if now - self._last_bale.get(evt, 0) < 30:           # avoid flooding admins
            return
        self._last_bale[evt] = now
        try:
            ad = self._rt.adapter()
        except Exception:
            return
        title, body = self._message(evt, p)
        for u in self._repo.list_users():
            if u["role"] in ("ADMIN", "SUPER_ADMIN") and not u["blocked"]:
                try:
                    ad.send_message(u["user_id"], f"⚠️ {title}\n{body}")
                except Exception as e:
                    log.info("could not notify admin %s: %s", u["user_id"], mask_text(str(e)))
