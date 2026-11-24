"""Owns the Bale client/adapter lifecycle, the token and the polling thread."""
from __future__ import annotations

import logging
import threading

import httpx

from app.core import events
from app.core.exceptions import BaleAuthError
from app.integrations.bale.adapter import BaleAPIAdapter, BotInfo, IncomingMessage
from app.integrations.bale.client import BaleClient
from app.integrations.bale.polling import BalePoller

log = logging.getLogger(__name__)
TOKEN_KEY = "bale_bot_token"


class BotRuntime:
    def __init__(self, repo, settings_mgr, secrets, bus: events.EventBus,
                 transport: httpx.BaseTransport | None = None):
        self._repo, self._sm, self._secrets, self._bus = repo, settings_mgr, secrets, bus
        self._transport = transport
        self._adapter: BaleAPIAdapter | None = None
        self._poller: BalePoller | None = None
        self._lock = threading.RLock()
        self._handler = None
        self.bot_info: BotInfo | None = None
        bus.subscribe(events.SETTINGS_CHANGED, self._on_settings)

    # ------------------------------------------------------------ token
    def has_token(self) -> bool:
        return bool(self._secrets.get(TOKEN_KEY))

    def set_token(self, token: str) -> None:
        self._secrets.set(TOKEN_KEY, token.strip())
        self._reset()

    def clear_token(self) -> None:
        self.stop_polling()
        self._secrets.delete(TOKEN_KEY)
        self._repo.clear_bot_account()
        self.bot_info = None
        self._reset()

    def masked_token(self) -> str:
        t = self._secrets.get(TOKEN_KEY) or ""
        return f"{t.split(':')[0]}:{'•' * 8}" if t else ""

    # ------------------------------------------------------------ adapter
    def _make_client(self, token: str) -> BaleClient:
        b = self._sm.settings.bale
        return BaleClient(token, api_base=b.api_base, connect_timeout=b.connect_timeout_s,
                          read_timeout=b.read_timeout_s, upload_timeout=b.upload_timeout_s,
                          retries=b.retry_count, backoff=b.retry_backoff_s, proxy=b.proxy or None,
                          transport=self._transport)

    def adapter(self) -> BaleAPIAdapter:
        with self._lock:
            if self._adapter is None:
                token = self._secrets.get(TOKEN_KEY)
                if not token:
                    raise BaleAuthError("no bot token configured", error_code=401)
                self._adapter = BaleAPIAdapter(self._make_client(token))
            return self._adapter

    def _reset(self) -> None:
        with self._lock:
            if self._adapter:
                self._adapter.close()
            self._adapter = None

    def _on_settings(self, _evt, **_kw) -> None:
        self._reset()

    def test_token(self, token: str) -> BotInfo:
        """Validate a token WITHOUT saving it."""
        a = BaleAPIAdapter(self._make_client(token.strip()))
        try:
            return a.get_me()
        finally:
            a.close()

    def connect(self) -> BotInfo:
        info = self.adapter().get_me()
        self.bot_info = info
        self._repo.set_bot_account(info.id, info.username, info.first_name)
        if info.username and self._sm.settings.bale.bot_username != info.username:
            self._sm.update({"bale": {"bot_username": info.username}})
        return info

    # ------------------------------------------------------------ polling
    def start_polling(self, handler=None) -> None:
        with self._lock:
            if handler:
                self._handler = handler
            if not self._handler or not self.has_token():
                return
            if self._poller and self._poller.is_running():
                return
            self._poller = BalePoller(self.adapter(), self._handler, self._repo, self._bus,
                                      lambda: self._sm.settings.bale.polling_interval_s)
            self._poller.start()

    def stop_polling(self) -> None:
        with self._lock:
            if self._poller:
                self._poller.stop()
                self._poller = None

    @property
    def status(self) -> str:
        return self._poller.status if self._poller else "stopped"

    def shutdown(self) -> None:
        self.stop_polling()
        self._reset()
