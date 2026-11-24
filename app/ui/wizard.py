"""10-step Setup Wizard. Every input has title, purpose, how-to, example, instant validation and a test button."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget, QFrame, QComboBox)

from app.core.config import LANGUAGES
from app.localization import LANG_NAMES
from app.security.access_control import Role
from app.services.caption import human_size
from app.ui.components.async_util import run_async
from app.ui.components.widgets import FieldRow, confirm, info_box

STEPS = ["welcome", "token", "connect", "channel", "access", "admins", "tempdir", "limits", "cleanup", "review"]
RESTART = 2


class SetupWizard(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.ctx = win, win.ctx
        self.t = self.ctx.tr
        self.setWindowTitle(self.t("wiz.title"))
        self.resize(780, 700)
        self.bot_ok = False
        self.chan_ok = False
        self.token_tested = False
        self.channel_info = None
        s = self.ctx.sm.settings
        draft = json.loads(self.ctx.repo.get_pref("wizard_draft", "{}") or "{}")
        self.draft = draft

        lay = QVBoxLayout(self)
        self.step_lbl = QLabel("")
        self.step_lbl.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, len(STEPS))
        self.bar.setTextVisible(False)
        self.h = QLabel("")
        self.h.setObjectName("title")
        lay.addWidget(self.step_lbl)
        lay.addWidget(self.bar)
        lay.addWidget(self.h)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.err = QLabel("")
        self.err.setWordWrap(True)
        self.err.setStyleSheet("color:#EF4444;")
        lay.addWidget(self.err)
        nav = QHBoxLayout()
        self.back = QPushButton(self.t("common.back"))
        self.back.clicked.connect(self.go_back)
        self.nxt = QPushButton(self.t("common.next"))
        self.nxt.setObjectName("primary")
        self.nxt.clicked.connect(self.go_next)
        cancel = QPushButton(self.t("wiz.save_exit"))
        cancel.clicked.connect(self._save_exit)
        nav.addWidget(cancel)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.nxt)
        lay.addLayout(nav)

        # --- build pages
        def page(*widgets) -> QWidget:
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            w = QWidget()
            l = QVBoxLayout(w)
            for x in widgets:
                l.addWidget(x)
            l.addStretch(1)
            sc.setWidget(w)
            self.stack.addWidget(sc)
            return w

        # 1 welcome
        intro = QTextBrowser()
        intro.setHtml(self.t("wiz.welcome_html"))
        intro.setMinimumHeight(260)
        self.lang = QComboBox()
        for k in LANGUAGES:
            self.lang.addItem(LANG_NAMES[k], k)
        self.lang.setCurrentIndex(LANGUAGES.index(s.general.language))
        self.lang.currentIndexChanged.connect(self._lang_changed)
        lrow = QLabel(self.t("field.language.t"))
        page(intro, lrow, self.lang)
        # 2 token
        self.f_token = FieldRow(self.t, "bot_token", "password", on_test=self._test_token, validator=self._v_token)
        if self.ctx.runtime.has_token():
            self.f_token.set_test_result(True, self.t("wiz.token_already", masked=self.ctx.runtime.masked_token()))
            self.token_tested = True
        page(self.f_token)
        # 3 connect
        self.conn_lbl = QLabel("")
        self.conn_lbl.setWordWrap(True)
        self.f_uname = FieldRow(self.t, "bot_username", "text", validator=lambda v: None, help_url=None)
        self.f_uname.set_value(s.bale.bot_username)
        retry = QPushButton(self.t("common.retry"))
        retry.clicked.connect(self._connect)
        page(self.conn_lbl, retry, self.f_uname)
        # 4 channel
        self.f_chan = FieldRow(self.t, "channel_id", "text", validator=self._v_chan)
        self.f_chan.set_value(draft.get("channel", ""))
        self.f_ctitle = FieldRow(self.t, "channel_title", "text", help_url=None)
        self.f_ctitle.set_value(draft.get("channel_title", ""))
        page(self.f_chan, self.f_ctitle)
        # 5 access
        self.access_lbl = QLabel(self.t("wiz.access_text"))
        self.access_lbl.setWordWrap(True)
        self.access_btn = QPushButton("📨 " + self.t("wiz.access_btn"))
        self.access_btn.clicked.connect(self._check_access)
        self.access_res = QLabel("")
        self.access_res.setWordWrap(True)
        self.skip_access = QCheckBox(self.t("wiz.skip_access"))
        page(self.access_lbl, self.access_btn, self.access_res, self.skip_access)
        # 6 admins
        self.f_admins = FieldRow(self.t, "admin_ids", "multiline", validator=self._v_admins, help_url=None)
        self.f_admins.set_value(draft.get("admins", "\n".join(str(u["user_id"]) for u in self.ctx.repo.list_users())))
        page(self.f_admins)
        # 7 temp dir
        self.f_dir = FieldRow(self.t, "download_dir", "path", validator=self._v_dir, on_test=self._test_dir, help_url=None)
        self.f_dir.set_value(s.download.directory)
        self.dir_info = QLabel("")
        page(self.f_dir, self.dir_info)
        # 8 limits
        self.f_max = FieldRow(self.t, "max_file_size", "int", minimum=1, maximum=4096, suffix="MB", help_url=None)
        self.f_max.set_value(s.download.max_file_size_mb)
        self.f_conc = FieldRow(self.t, "concurrent", "int", minimum=1, maximum=8, help_url=None)
        self.f_conc.set_value(s.download.concurrent_downloads)
        self.f_bw = FieldRow(self.t, "bandwidth", "int", minimum=0, maximum=10_000_000, suffix="KB/s", help_url=None)
        self.f_bw.set_value(s.download.bandwidth_limit_kbps)
        self.f_types = FieldRow(self.t, "allowed_types", "multicheck", help_url=None)
        self.f_types.set_value(s.download.allowed_types)
        page(self.f_max, self.f_conc, self.f_bw, self.f_types)
        # 9 cleanup
        note = QLabel(self.t("wiz.cleanup_note"))
        note.setWordWrap(True)
        self.f_priv = FieldRow(self.t, "privacy_mode", "bool", help_url=None)
        self.f_priv.set_value(s.cleanup.privacy_mode)
        self.f_del = FieldRow(self.t, "delete_after_upload", "bool", help_url=None)
        self.f_del.set_value(True)
        self.f_del.lock(True)
        self.f_cint = FieldRow(self.t, "cleanup_interval", "int", minimum=1, maximum=1440, suffix="min", help_url=None)
        self.f_cint.set_value(s.cleanup.interval_min)
        self.f_orph = FieldRow(self.t, "orphan_age", "int", minimum=1, maximum=720, suffix="h", help_url=None)
        self.f_orph.set_value(s.cleanup.orphan_max_age_hours)
        page(note, self.f_del, self.f_priv, self.f_cint, self.f_orph)
        # 10 review
        self.review = QTextBrowser()
        self.confirm_post = QCheckBox(self.t("chan.confirm_authorized"))
        page(self.review, self.confirm_post)

        self.idx = min(int(self.ctx.repo.get_pref("wizard_step", "0") or 0), len(STEPS) - 1)
        if self.idx >= 2 and not self.ctx.runtime.has_token():
            self.idx = 1
        self._show()

    # ------------------------------------------------------------ validators
    def _v_token(self, v):
        if not v:
            return None if self.ctx.runtime.has_token() else self.t("err.required")
        return None if re.fullmatch(r"\d{4,}:[A-Za-z0-9_\-]{16,}", v) else self.t("err.token_format")

    def _v_chan(self, v):
        v = (v or "").strip()
        if not v:
            return self.t("err.required")
        return None if (v.lstrip("-").isdigit() or re.fullmatch(r"@?[A-Za-z0-9_]{3,}", v)) else self.t("err.channel_format")

    def _v_admins(self, v):
        for tok in re.split(r"[\s,;،]+", v or ""):
            if tok and not tok.isdigit():
                return self.t("err.numeric_id") + f" ({tok[:20]})"
        return None

    def _v_dir(self, v):
        return self.t("err.required") if not v else None

    # ------------------------------------------------------------ tests
    def _test_token(self) -> None:
        tok = self.f_token.value()
        if not tok:
            self.f_token.set_error(self.t("err.required"))
            return
        if not self.f_token.validate():
            return
        self.f_token.set_test_result(True, self.t("common.testing"))

        def done(res, err):
            if err:
                self.token_tested = False
                self.f_token.set_test_result(False, self.t("err.token_rejected", detail=str(err)))
            else:
                self.token_tested = True
                self.f_token.set_test_result(True, self.t("set.token_ok", name=res.first_name, username=res.username))
        run_async(lambda: self.ctx.runtime.test_token(tok), done)

    def _connect(self) -> None:
        self.conn_lbl.setText(self.t("common.testing"))
        self.bot_ok = False

        def done(res, err):
            if err:
                self.conn_lbl.setStyleSheet("color:#EF4444;")
                self.conn_lbl.setText("✖ " + self.t("wiz.conn_fail", detail=str(err)))
            else:
                self.bot_ok = True
                self.conn_lbl.setStyleSheet("color:#22C55E;")
                self.conn_lbl.setText("✔ " + self.t("wiz.conn_ok", name=res.first_name, username=res.username, id=res.id))
                self.f_uname.set_value(res.username)
        run_async(self.ctx.runtime.connect, done)

    def _check_access(self) -> None:
        cid = self.f_chan.value()
        if not confirm(self, self.t("chan.probe_title"), self.t("chan.probe_text"), self.t("common.yes"), self.t("common.no")):
            return
        self.access_res.setText(self.t("common.testing"))

        def done(res, err):
            self.chan_ok = False
            if err:
                self.access_res.setStyleSheet("color:#EF4444;")
                self.access_res.setText("✖ " + str(err))
            elif res.ok and res.can_post:
                self.chan_ok = True
                self.channel_info = res
                self.access_res.setStyleSheet("color:#22C55E;")
                extra = "" if res.is_channel else "\n⚠ " + self.t("wiz.not_channel")
                self.access_res.setText("✔ " + self.t("chan.test_ok", title=res.title or "-") + (f"  (id {res.numeric_id})" if res.numeric_id else "") + extra)
                if res.title and not self.f_ctitle.value():
                    self.f_ctitle.set_value(res.title)
            else:
                self.access_res.setStyleSheet("color:#EF4444;")
                self.access_res.setText("✖ " + self.t("chan.test_fail", detail=res.detail or ""))
        run_async(lambda: self.ctx.runtime.adapter().check_channel(cid, True), done)

    def _test_dir(self) -> None:
        p = Path(self.f_dir.value())
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".write_test"
            probe.write_text("x")
            probe.unlink()
            free = shutil.disk_usage(p).free
            self.f_dir.set_test_result(True, self.t("wiz.dir_ok", free=human_size(free)))
        except OSError as e:
            self.f_dir.set_test_result(False, self.t("wiz.dir_fail", detail=str(e)))

    # ------------------------------------------------------------ navigation
    def _lang_changed(self) -> None:
        lang = self.lang.currentData()
        if lang != self.ctx.sm.settings.general.language:
            self._save_draft()
            self.ctx.sm.update({"general": {"language": lang}})
            self.win.apply_look(rebuild=True)
            self.done(RESTART)

    def _show(self) -> None:
        self.stack.setCurrentIndex(self.idx)
        key = STEPS[self.idx]
        self.step_lbl.setText(self.t("wiz.step", i=self.idx + 1, n=len(STEPS)))
        self.bar.setValue(self.idx + 1)
        self.h.setText(self.t(f"wiz.s.{key}"))
        self.back.setEnabled(self.idx > 0)
        self.nxt.setText(self.t("wiz.activate") if self.idx == len(STEPS) - 1 else self.t("common.next"))
        self.err.setText("")
        if key == "connect":
            self._connect()
        if key == "review":
            self._fill_review()
        self.ctx.repo.set_pref("wizard_step", str(self.idx))

    def _save_draft(self) -> None:
        self.ctx.repo.set_pref("wizard_draft", json.dumps({
            "channel": self.f_chan.value(), "channel_title": self.f_ctitle.value(), "admins": self.f_admins.value()}))

    def _save_exit(self) -> None:
        self._save_draft()
        self.reject()

    def go_back(self) -> None:
        if self.idx > 0:
            self.idx -= 1
            self._show()

    def _fail(self, msg: str) -> bool:
        self.err.setText("✖ " + msg)
        return False

    def _can_leave(self) -> bool:
        key = STEPS[self.idx]
        if key == "token":
            if not self.f_token.validate():
                return self._fail(self.t("err.token_format"))
            tok = self.f_token.value()
            if tok and not self.token_tested:
                return self._fail(self.t("wiz.test_first"))
            if tok:
                self.ctx.runtime.set_token(tok)                 # persisted to the secure store right away
                self.f_token.w.clear()
                self.ctx.runtime.stop_polling()
            elif not self.ctx.runtime.has_token():
                return self._fail(self.t("err.required"))
        elif key == "connect":
            if not self.bot_ok:
                return self._fail(self.t("wiz.need_conn"))
            if self.f_uname.value():
                self.ctx.sm.update({"bale": {"bot_username": self.f_uname.value().lstrip("@")}})
        elif key == "channel":
            if not self.f_chan.validate():
                return self._fail(self.t("err.channel_format"))
            self._save_draft()
        elif key == "access":
            if not self.chan_ok and not self.skip_access.isChecked():
                return self._fail(self.t("wiz.need_access"))
        elif key == "admins":
            if not self.f_admins.validate():
                return self._fail(self.t("err.numeric_id"))
            self._save_draft()
        elif key == "tempdir":
            if not self.f_dir.validate():
                return self._fail(self.t("err.required"))
            try:
                Path(self.f_dir.value()).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return self._fail(self.t("wiz.dir_fail", detail=str(e)))
        elif key == "limits":
            if not self.f_types.value():
                return self._fail(self.t("wiz.need_type"))
        return True

    def go_next(self) -> None:
        if not self._can_leave():
            return
        if self.idx == len(STEPS) - 1:
            return self._finish()
        self.idx += 1
        self._show()

    # ------------------------------------------------------------ review / activate
    def _admin_list(self) -> list[int]:
        return [int(x) for x in re.split(r"[\s,;،]+", self.f_admins.value()) if x.isdigit()]

    def _fill_review(self) -> None:
        t = self.t
        rows = [(t("field.bot_token.t"), self.ctx.runtime.masked_token() + f" ({self.ctx.secrets.backend_name})"),
                (t("field.bot_username.t"), "@" + self.f_uname.value().lstrip("@")),
                (t("field.channel_id.t"), self.f_chan.value() + (f" – {self.f_ctitle.value()}" if self.f_ctitle.value() else "")),
                (t("wiz.access"), "✔" if self.chan_ok else "⚠ " + t("wiz.not_verified")),
                (t("field.admin_ids.t"), ", ".join(map(str, self._admin_list())) or "—"),
                (t("field.download_dir.t"), self.f_dir.value()),
                (t("field.max_file_size.t"), f"{self.f_max.value()} MB"),
                (t("field.concurrent.t"), str(self.f_conc.value())),
                (t("field.bandwidth.t"), f"{self.f_bw.value()} KB/s" if self.f_bw.value() else t("common.unlimited")),
                (t("field.privacy_mode.t"), t("common.yes") if self.f_priv.value() else t("common.no")),
                (t("field.delete_after_upload.t"), t("common.yes"))]
        self.review.setHtml("<table cellpadding=6>" + "".join(f"<tr><td><b>{a}</b></td><td>{b}</td></tr>" for a, b in rows) + "</table>")

    def _finish(self) -> None:
        if not self.confirm_post.isChecked():
            return self._fail(self.t("chan.need_confirm")) and None
        s = {"download": {"directory": self.f_dir.value(), "max_file_size_mb": self.f_max.value(),
                          "concurrent_downloads": self.f_conc.value(), "bandwidth_limit_kbps": self.f_bw.value(),
                          "allowed_types": self.f_types.value()},
             "cleanup": {"privacy_mode": self.f_priv.value(), "interval_min": self.f_cint.value(),
                         "orphan_max_age_hours": self.f_orph.value()},
             "general": {"first_run_done": True}}
        try:
            self.ctx.sm.update(s)
        except Exception as e:
            return self._fail(str(e)) and None
        cid = self.f_chan.value().strip()
        if not any(c["chat_id"] == cid for c in self.ctx.repo.list_channels()):
            ch = self.ctx.repo.add_channel(cid, self.f_ctitle.value(), "", True, [])
            self.ctx.repo.update_channel(ch["id"], status="ok" if self.chan_ok else "unverified")
        for uid in self._admin_list():
            if not self.ctx.repo.get_user(uid):
                self.ctx.add_admin(uid)
        self.ctx.repo.add_activity("setup_completed", "", 0, "system")
        self.ctx.repo.set_pref("wizard_step", "0")
        self.ctx.repo.set_pref("wizard_draft", "{}")
        self.ctx.start_bot()
        self.accept()
