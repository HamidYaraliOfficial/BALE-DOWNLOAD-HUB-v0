"""Command handling for the Bale bot. Only uses features the documented Bot API really offers
(plain text commands + sendMessage). Confirmations are text commands, not inline buttons, because the
documented API has no answerCallbackQuery."""
from __future__ import annotations

import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.constants import ACTIVE_STATUSES, LIVE_STATUSES, JobStatus
from app.core.exceptions import AccessDenied, RateLimited
from app.core.logger import mask_text
from app.downloader.validators import dedupe_links, extract_links
from app.integrations.bale.adapter import IncomingMessage
from app.security.access_control import AccessController, RateLimiter, Role
from app.services.caption import human_size

log = logging.getLogger(__name__)
MAX_LINKS_PER_MESSAGE = 10
PENDING_TTL = 600


class BotService:
    def __init__(self, repo, settings_mgr, runtime, downloads, access: AccessController, tr, cleanup=None):
        self.repo, self.sm, self.rt, self.dl, self.access, self.tr = repo, settings_mgr, runtime, downloads, access, tr
        self.limiter = RateLimiter(limit=settings_mgr.settings.security.rate_limit_per_min)
        self._stranger = RateLimiter(limit=2, window=60)
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="bot-links")
        self._pending: dict[str, dict] = {}
        self.cleanup = cleanup

    def t(self, key: str, **kw) -> str:
        return self.tr.tr_in(self.sm.settings.general.language, key, **kw)

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self.rt.adapter().send_message(chat_id, text)
        except Exception as e:
            log.warning("bot reply failed: %s", mask_text(str(e)))

    # ------------------------------------------------------------------ entry
    def handle(self, msg: IncomingMessage) -> None:
        if msg.chat_type != "private" or msg.user_id is None or not msg.text:
            return                                    # groups / channels / non-text are ignored
        self.limiter.configure(self.sm.settings.security.rate_limit_per_min)
        uid = msg.user_id
        role = self.access.get_role(uid)
        if role is None:
            self.repo.add_activity("unauthorized_request", f"user {uid} (@{msg.username}) sent a message", uid, "security")
            try:
                self._stranger.check(uid)
                self._reply(msg.chat_id, self.t("bot.not_authorized", user_id=uid))
            except RateLimited:
                pass
            return
        try:
            self.limiter.check(uid)
        except RateLimited:
            self.repo.add_activity("rate_limited", f"user {uid}", uid, "security")
            self._reply(msg.chat_id, self.t("bot.rate_limited"))
            return
        text = msg.text.strip()
        if text.startswith("/"):
            self._command(msg, role, text)
        else:
            links = extract_links(text)
            if links:
                self._pool.submit(self._links, msg, role, links)
            else:
                self._reply(msg.chat_id, self.t("bot.send_link_hint"))

    # ------------------------------------------------------------------ commands
    def _command(self, msg: IncomingMessage, role: Role, text: str) -> None:
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]
        uid, cid = msg.user_id, msg.chat_id
        try:
            if cmd in ("/start", "/help"):
                self._reply(cid, self.t("bot.start" if cmd == "/start" else "bot.help", role=role.name))
            elif cmd == "/status":
                self.access.require(uid, "view_status")
                self._reply(cid, self._status_text())
            elif cmd == "/queue":
                self.access.require(uid, "view_status")
                self._reply(cid, self._queue_text())
            elif cmd == "/cancel":
                self.access.require(uid, "control_queue")
                self._reply(cid, self._cancel(uid, args))
            elif cmd in ("/pause", "/resume"):
                self.access.require(uid, "control_queue")
                self._reply(cid, self._pause_resume(uid, cmd, args))
            elif cmd in ("/confirm", "/reject"):
                self.access.require(uid, "submit_link")
                self._reply(cid, self._confirm(uid, cmd, args))
            elif cmd in ("/users", "/adduser", "/removeuser", "/block", "/unblock"):
                self.access.require(uid, "manage_users")
                self._reply(cid, self._admin(uid, cmd, args))
            else:
                self._reply(cid, self.t("bot.unknown_command"))
        except AccessDenied:
            self.repo.add_activity("access_denied", f"{cmd} by {uid}", uid, "security")
            self._reply(cid, self.t("bot.forbidden"))

    def _status_text(self) -> str:
        st = self.repo.stats()
        u = self.cleanup.usage() if self.cleanup else {"disk_free": 0}
        bot = self.rt.status
        return self.t("bot.status", active=st["active"], queued=st["queued"], done=st["completed"],
                      failed=st["failed"], free=human_size(u["disk_free"]), bot=bot,
                      paused=self.t("common.yes") if self.dl.queue.paused else self.t("common.no"))

    def _queue_text(self) -> str:
        jobs = self.repo.queue_snapshot()[:10]
        if not jobs:
            return self.t("bot.queue_empty")
        lines = []
        for j in jobs:
            pct = f"{(j['size_done'] / j['size_total'] * 100):.0f}%" if j["size_total"] else "-"
            lines.append(f"{j['id'][:8]} · {self.t('status.' + j['status'])} · {pct} · {(j['filename'] or '')[:40]}")
        return "\n".join(lines)

    def _find(self, prefix: str) -> dict | None:
        m = [j for j in self.repo.list_jobs(statuses=list(LIVE_STATUSES), limit=2000) if j["id"].startswith(prefix)]
        return m[0] if len(m) == 1 else None

    def _owns(self, uid: int, job: dict) -> bool:
        return job["requester_id"] == uid or self.access.is_authorized(uid, "cancel_any")

    def _cancel(self, uid: int, args: list[str]) -> str:
        if not args:
            return self.t("bot.cancel_usage")
        if args[0].lower() == "all":
            self.access.require(uid, "cancel_any")
            return self.t("bot.cancelled_n", n=self.dl.queue.cancel_all())
        j = self._find(args[0])
        if not j:
            return self.t("bot.job_not_found")
        if not self._owns(uid, j):
            raise AccessDenied("not your job")
        self.dl.cancel(j["id"])
        return self.t("bot.cancelled", id=j["id"][:8])

    def _pause_resume(self, uid: int, cmd: str, args: list[str]) -> str:
        if args:
            j = self._find(args[0])
            if not j:
                return self.t("bot.job_not_found")
            if not self._owns(uid, j):
                raise AccessDenied("not your job")
            (self.dl.pause if cmd == "/pause" else self.dl.resume)(j["id"])
            return self.t("bot.job_paused" if cmd == "/pause" else "bot.job_resumed", id=j["id"][:8])
        self.access.require(uid, "cancel_any")           # whole-queue control is an admin action
        if cmd == "/pause":
            self.dl.queue.pause_queue("bot")
            return self.t("bot.queue_paused")
        self.dl.queue.resume_queue()
        return self.t("bot.queue_resumed")

    def _admin(self, uid: int, cmd: str, args: list[str]) -> str:
        if cmd == "/users":
            rows = [f"{u['user_id']} · {u['role']}{' · BLOCKED' if u['blocked'] else ''} · {u['display_name']}"
                    for u in self.repo.list_users()]
            return "\n".join(rows) or self.t("bot.no_users")
        if not args or not args[0].lstrip("-").isdigit():
            return self.t("bot.admin_usage")
        target = int(args[0])
        tr = self.repo.get_user(target)
        if tr and Role.parse(tr["role"]) >= Role.ADMIN and not self.access.is_authorized(uid, "manage_admins"):
            raise AccessDenied("only a Super Admin can modify admins")
        if cmd == "/adduser":
            role = Role.parse(args[1]) if len(args) > 1 and args[1].upper() in Role.__members__ else Role.OPERATOR
            if not self.access.can_assign(uid, role):
                raise AccessDenied("cannot assign that role")
            self.repo.add_user(target, "", role.name)
            self.repo.add_activity("user_added", f"{target} as {role.name}", uid, "user")
            return self.t("bot.user_added", id=target, role=role.name)
        if cmd == "/removeuser":
            self.repo.remove_user(target)
            self.repo.add_activity("user_removed", str(target), uid, "user")
            return self.t("bot.user_removed", id=target)
        if cmd in ("/block", "/unblock"):
            self.repo.update_user(target, blocked=(cmd == "/block"))
            self.repo.add_activity(cmd[1:], str(target), uid, "user")
            return self.t("bot.user_blocked" if cmd == "/block" else "bot.user_unblocked", id=target)
        return self.t("bot.unknown_command")

    # ------------------------------------------------------------------ links
    def _links(self, msg: IncomingMessage, role: Role, links: list[str]) -> None:
        uid, cid = msg.user_id, msg.chat_id
        if role < Role.OPERATOR:
            self._reply(cid, self.t("bot.forbidden"))
            return
        uniq, dups = dedupe_links(links)
        uniq = uniq[:MAX_LINKS_PER_MESSAGE]
        lines = []
        for url in uniq:
            if self.sm.settings.bale.require_confirmation:
                lines.append(self._ask_confirmation(uid, url))
                continue
            r = self.dl.add_job(url, source="bot", requester_id=uid)
            lines.append(self._result_line(r))
        lines += [self.t("bot.dup_in_message", url=u[:60]) for u in dups[:3]]
        self._reply(cid, "\n".join(lines))

    def _result_line(self, r) -> str:
        short = r.url[:50]
        if r.ok:
            return self.t("bot.queued", id=r.job["id"][:8], name=r.job["filename"] or "", size=human_size(r.job["size_total"]))
        return self.t("bot.rejected", url=short, reason=self.t("error." + r.code) if self.tr.has("error." + r.code, self.sm.settings.general.language) else r.code)

    def _ask_confirmation(self, uid: int, url: str) -> str:
        try:
            probe = self.dl.preview(url)
        except Exception as e:
            code = getattr(e, "code", "probe_failed")
            return self.t("bot.rejected", url=url[:50], reason=self.t("error." + code))
        if not probe.supported:
            return self.t("bot.rejected", url=url[:50], reason=self.t("error." + probe.reason_code))
        token = secrets.token_hex(3)
        now = time.time()
        for k in [k for k, v in self._pending.items() if now - v["ts"] > PENDING_TTL]:
            self._pending.pop(k, None)
        self._pending[token] = {"uid": uid, "url": url, "probe": probe, "ts": now}
        return self.t("bot.confirm_ask", name=probe.filename, size=human_size(probe.size), type=probe.category, token=token)

    def _confirm(self, uid: int, cmd: str, args: list[str]) -> str:
        p = self._pending.get(args[0]) if args else None
        if not p or p["uid"] != uid:
            return self.t("bot.confirm_unknown")
        self._pending.pop(args[0], None)
        if cmd == "/reject":
            return self.t("bot.confirm_rejected")
        r = self.dl.add_job(p["url"], source="bot", requester_id=uid, probe=p["probe"])
        return self._result_line(r)
