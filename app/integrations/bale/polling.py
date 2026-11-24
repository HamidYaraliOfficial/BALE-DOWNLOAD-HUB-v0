"""Long-running getUpdates loop (the documented Bale API has no `timeout` parameter, so this is
short polling with a configurable interval). Offsets are persisted to avoid re-handling updates."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from app.core import events
from app.core.exceptions import BaleAuthError, BaleNetworkError, BaleApiError
from app.integrations.bale.adapter import BaleAPIAdapter, IncomingMessage

log = logging.getLogger(__name__)
OFFSET_KEY = "bale_update_offset"


class BalePoller:
    def __init__(self, adapter: BaleAPIAdapter, handler: Callable[[IncomingMessage], None], repo, bus,
                 interval_getter: Callable[[], float], fail_threshold: int = 3):
        self._a, self._handler, self._repo, self._bus = adapter, handler, repo, bus
        self._interval = interval_getter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fails = 0
        self._threshold = fail_threshold
        self.status = "stopped"
        self._notified_down = False

    def _set_status(self, st: str, detail: str = "") -> None:
        if st != self.status:
            self.status = st
            self._bus.publish(events.BOT_STATUS, status=st, detail=detail)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bale-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        self._set_status("stopped")

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def poll_once(self) -> int:
        """One polling cycle; returns the number of updates handled. Public for tests."""
        raw_off = self._repo.get_setting(OFFSET_KEY)
        offset = int(raw_off) if raw_off else None
        updates = self._a.get_updates(offset=offset, limit=50)
        top = None
        for u in updates:
            top = u.update_id if top is None else max(top, u.update_id)
            if u.chat_id:  # real message
                try:
                    self._handler(u)
                except Exception:
                    log.exception("bot handler crashed (update %s)", u.update_id)
        if top is not None:
            self._repo.set_setting(OFFSET_KEY, str(top + 1))
        return len(updates)

    def _run(self) -> None:
        self._set_status("connecting")
        try:
            if self._a.get_webhook_url():
                log.info("a webhook is configured on this bot – disabling it to use getUpdates")
                self._a.disable_webhook()
        except BaleAuthError as e:
            self._set_status("error", str(e))
            self._bus.publish(events.CONNECTION_ERROR, detail=str(e))
            return
        except (BaleApiError, BaleNetworkError) as e:
            log.warning("webhook check failed: %s", e)
        while not self._stop.is_set():
            try:
                self.poll_once()
                self._fails = 0
                self._notified_down = False
                self._set_status("connected")
            except BaleAuthError as e:
                self._set_status("error", str(e))
                self._bus.publish(events.CONNECTION_ERROR, detail=str(e))
                return                      # an invalid token will not fix itself – stop
            except (BaleNetworkError, BaleApiError) as e:
                self._fails += 1
                log.warning("polling failed (%s): %s", self._fails, e)
                if self._fails >= self._threshold:
                    self._set_status("error", str(e))
                    if not self._notified_down:
                        self._notified_down = True
                        self._bus.publish(events.BOT_DISCONNECTED, detail=str(e))
            except Exception:
                log.exception("unexpected polling error")
            wait = self._interval() * (min(self._fails, 5) + 1 if self._fails else 1)
            self._stop.wait(min(wait, 60))
