"""BaleAPIAdapter – the ONLY class the rest of the application uses to talk to Bale.

If Bale changes its API, only this package needs to change. Every method below exists in the
official documentation (docs.bale.ai); nothing is invented. Things the API does NOT offer
(and which this adapter therefore does not pretend to offer): scheduled posts, getChatMember /
getChatAdministrators, answerCallbackQuery, thumbnails for sendDocument/sendVideo, long-poll `timeout`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.constants import BALE_MAX_CAPTION, BALE_MAX_TEXT
from app.core.exceptions import BaleApiError
from app.integrations.bale.client import BaleClient

ProgressCb = Callable[[int, int], None]


@dataclass
class BotInfo:
    id: int
    username: str
    first_name: str


@dataclass
class ChatInfo:
    id: int | str
    type: str
    title: str = ""
    username: str = ""


@dataclass
class ChannelCheck:
    ok: bool
    exists: bool = False
    is_channel: bool = False
    can_post: bool | None = None       # None = not probed
    title: str = ""
    username: str = ""
    numeric_id: str = ""
    detail: str = ""


@dataclass
class IncomingMessage:
    update_id: int
    message_id: int
    chat_id: int
    chat_type: str
    user_id: int | None
    username: str
    first_name: str
    text: str
    date: int = 0
    raw: dict = field(default_factory=dict, repr=False)


def normalize_chat_id(chat_id: str | int) -> str | int:
    """Numeric ids (incl. negative) become int; `@name` stays a string; bare `name` gets '@'."""
    if isinstance(chat_id, int):
        return chat_id
    s = str(chat_id).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    if s.startswith("https://ble.ir/"):
        s = s.rsplit("/", 1)[-1]
    return s if s.startswith("@") else f"@{s}"


class BaleAPIAdapter:
    def __init__(self, client: BaleClient):
        self._c = client

    def close(self) -> None:
        self._c.close()

    # --- identity -------------------------------------------------------------------------
    def get_me(self) -> BotInfo:
        r = self._c.call("getMe")
        return BotInfo(id=int(r.get("id", 0)), username=r.get("username", "") or "",
                       first_name=r.get("first_name", "") or "")

    # --- chats ----------------------------------------------------------------------------
    def get_chat(self, chat_id: str | int) -> ChatInfo:
        r = self._c.call("getChat", {"chat_id": normalize_chat_id(chat_id)})
        return ChatInfo(id=r.get("id"), type=r.get("type", ""), title=r.get("title", "") or "",
                        username=r.get("username", "") or "")

    def get_chat_members_count(self, chat_id: str | int) -> int:
        return int(self._c.call("getChatMembersCount", {"chat_id": normalize_chat_id(chat_id)}))

    def check_channel(self, chat_id: str | int, probe_post: bool = True) -> ChannelCheck:
        """Existence via getChat; posting rights via a real test message that is deleted again.
        (The documented API has no 'get my permissions' call, so a probe is the only honest test.)"""
        try:
            info = self.get_chat(chat_id)
        except BaleApiError as e:
            return ChannelCheck(ok=False, detail=str(e))
        res = ChannelCheck(ok=True, exists=True, is_channel=(info.type == "channel"), title=info.title,
                           username=info.username, numeric_id=str(info.id))
        if not probe_post:
            return res
        try:
            msg_id = self.send_message(info.id if info.id else chat_id, "✅ Bale Download Hub – connection test")
            res.can_post = True
            try:
                self.delete_message(info.id if info.id else chat_id, msg_id)
            except BaleApiError:
                res.detail = "test message was sent but could not be deleted (missing delete permission)"
        except BaleApiError as e:
            res.can_post, res.ok, res.detail = False, False, str(e)
        return res

    # --- messages -------------------------------------------------------------------------
    @staticmethod
    def _msg_id(result: dict) -> int:
        return int((result or {}).get("message_id", 0))

    def send_message(self, chat_id: str | int, text: str, reply_to: int | None = None) -> int:
        r = self._c.call("sendMessage", {"chat_id": normalize_chat_id(chat_id), "text": text[:BALE_MAX_TEXT],
                                         "reply_to_message_id": reply_to})
        return self._msg_id(r)

    def delete_message(self, chat_id: str | int, message_id: int) -> bool:
        return bool(self._c.call("deleteMessage", {"chat_id": normalize_chat_id(chat_id),
                                                   "message_id": message_id}))

    def _send_file(self, method: str, field_name: str, chat_id, path: str, caption: str | None,
                   progress: ProgressCb | None) -> int:
        params = {"chat_id": normalize_chat_id(chat_id)}
        if caption:
            params["caption"] = caption[:BALE_MAX_CAPTION]
        r = self._c.call(method, params, files={field_name: path}, progress=progress)
        return self._msg_id(r)

    def send_document(self, chat_id, path: str, caption: str | None = None, progress: ProgressCb | None = None) -> int:
        return self._send_file("sendDocument", "document", chat_id, path, caption, progress)

    def send_photo(self, chat_id, path: str, caption: str | None = None, progress: ProgressCb | None = None) -> int:
        return self._send_file("sendPhoto", "photo", chat_id, path, caption, progress)

    def send_video(self, chat_id, path: str, caption: str | None = None, progress: ProgressCb | None = None) -> int:
        return self._send_file("sendVideo", "video", chat_id, path, caption, progress)

    def send_audio(self, chat_id, path: str, caption: str | None = None, progress: ProgressCb | None = None) -> int:
        return self._send_file("sendAudio", "audio", chat_id, path, caption, progress)

    # --- updates --------------------------------------------------------------------------
    def get_webhook_url(self) -> str:
        r = self._c.call("getWebhookInfo") or {}
        return r.get("url", "") or ""

    def disable_webhook(self) -> None:
        """Documented way to switch off a webhook: setWebhook with an empty url."""
        self._c.call("setWebhook", {"url": ""})

    def get_updates(self, offset: int | None = None, limit: int = 50) -> list[IncomingMessage]:
        raw = self._c.call("getUpdates", {"offset": offset, "limit": limit}) or []
        out: list[IncomingMessage] = []
        for u in raw:
            msg: dict[str, Any] | None = u.get("message")
            uid = int(u.get("update_id", 0))
            if not msg:
                # callback_query / edited_message are acknowledged (offset moves on) but not acted upon
                out.append(IncomingMessage(uid, 0, 0, "", None, "", "", "", raw=u))
                continue
            frm = msg.get("from") or {}
            chat = msg.get("chat") or {}
            out.append(IncomingMessage(
                update_id=uid, message_id=int(msg.get("message_id", 0)), chat_id=int(chat.get("id", 0)),
                chat_type=chat.get("type", ""), user_id=int(frm["id"]) if frm.get("id") is not None else None,
                username=frm.get("username", "") or "", first_name=frm.get("first_name", "") or "",
                text=msg.get("text", "") or "", date=int(msg.get("date", 0)), raw=u))
        return out
