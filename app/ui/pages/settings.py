from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QTabWidget, QVBoxLayout, QWidget, QFrame, QComboBox, QDialog)

from app.core.config import LANGUAGES, THEMES
from app.core.exceptions import BackupError, ConfigError, HubError
from app.localization import LANG_NAMES
from app.services.caption import VARIABLES, human_size, render_caption
from app.ui.components.async_util import run_async
from app.ui.components.widgets import FieldRow, confirm, info_box
from app.ui.pages.base import Page

CRITICAL = {"api.enabled", "download.directory", "download.concurrent_downloads", "download.max_file_size_mb", "cleanup.privacy_mode",
            "logging.db_retention_days", "bale.api_base", "bale.proxy"}


def _tab(widget_list: list[QWidget]) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setSpacing(10)
    for w in widget_list:
        lay.addWidget(w)
    lay.addStretch(1)
    sc.setWidget(body)
    return sc


class SettingsPage(Page):
    title_key = "nav.settings"

    def __init__(self, win):
        super().__init__(win)
        t = self.t
        self.header(t("set.title"), t("set.sub"))
        self.fields: dict[str, FieldRow] = {}       # "section.key" -> row
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)

        def F(path: str, fid: str, kind: str, **kw) -> FieldRow:
            row = FieldRow(self.tr_, fid, kind, **kw)
            self.fields[path] = row
            return row

        # ---------------- Bot
        self.token = FieldRow(self.tr_, "bot_token", "password", on_test=self._test_token, validator=self._v_token)
        self.token_state = QLabel("")
        self.token_state.setObjectName("muted")
        tok_btns = QHBoxLayout()
        b1 = QPushButton(t("set.save_token"))
        b1.setObjectName("primary")
        b1.clicked.connect(self._save_token)
        b2 = QPushButton(t("set.remove_token"))
        b2.setObjectName("danger")
        b2.clicked.connect(self._remove_token)
        tok_btns.addWidget(b1)
        tok_btns.addWidget(b2)
        tok_btns.addStretch(1)
        tok_box = QWidget()
        tl = QVBoxLayout(tok_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.token)
        tl.addWidget(self.token_state)
        tl.addLayout(tok_btns)
        self.tabs.addTab(_tab([
            tok_box,
            F("bale.bot_username", "bot_username", "text", validator=self._v_uname),
            F("bale.bot_enabled", "bot_enabled", "bool", help_url=None),
            F("bale.require_confirmation", "require_confirmation", "bool", help_url=None),
            F("security.rate_limit_per_min", "rate_limit", "int", minimum=1, maximum=600, suffix="/min", help_url=None),
            F("security.user_daily_quota_mb", "user_quota_default", "int", minimum=0, maximum=1_000_000, suffix="MB", help_url=None),
            F("api.enabled", "api_enabled", "bool", help_url=None),
            F("api.port", "api_port", "int", minimum=1024, maximum=65535, help_url=None),
            self._api_box(),
        ]), t("set.tab.bot").replace("&", "&&"))

        # ---------------- Downloads
        self.tabs.addTab(_tab([
            F("download.directory", "download_dir", "path", validator=self._v_dir, help_url=None),
            F("download.max_file_size_mb", "max_file_size", "int", minimum=1, maximum=4096, suffix="MB", help_url=None),
            F("download.concurrent_downloads", "concurrent", "int", minimum=1, maximum=8, help_url=None),
            F("download.allowed_types", "allowed_types", "multicheck", help_url=None),
            F("download.bandwidth_limit_kbps", "bandwidth", "int", minimum=0, maximum=10_000_000, suffix="KB/s", help_url=None),
            F("download.segments", "segments", "int", minimum=1, maximum=16, help_url=None),
            F("download.chunk_size_kb", "chunk_size", "int", minimum=16, maximum=8192, suffix="KB", help_url=None),
            F("download.min_free_disk_mb", "min_free_disk", "int", minimum=0, maximum=1_000_000, suffix="MB", help_url=None),
            F("download.split_large_files", "split_large", "bool", help_url=None),
            F("download.priority_small_first", "small_first", "bool", help_url=None),
            F("download.use_ytdlp", "use_ytdlp", "bool", help_url=None),
        ]), t("set.tab.downloads").replace("&", "&&"))

        # ---------------- Publishing & media
        self.caption = F("publish.default_caption", "default_caption", "multiline", help_url=None)
        self.caption_preview = QLabel("")
        self.caption_preview.setObjectName("hint")
        self.caption_preview.setWordWrap(True)
        self.caption.changed.connect(self._preview_caption)
        vars_lbl = QLabel(t("set.caption_vars") + " " + " ".join("{%s}" % v for v in VARIABLES))
        vars_lbl.setObjectName("hint")
        vars_lbl.setWordWrap(True)
        tpl_btn = QPushButton(t("set.edit_templates"))
        tpl_btn.clicked.connect(self._edit_templates)
        self.tabs.addTab(_tab([
            F("publish.auto_publish", "auto_publish", "bool", help_url=None),
            F("publish.delete_after_upload", "delete_after_upload", "bool", help_url=None),
            F("publish.duplicate_detection", "duplicate_detection", "bool", help_url=None),
            F("cleanup.privacy_mode", "privacy_mode", "bool", help_url=None),
            self.caption, vars_lbl, self.caption_preview, tpl_btn,
            F("media.make_thumbnails", "make_thumbnails", "bool", help_url=None),
            F("media.convert_images_to", "convert_images", "combo", help_url=None,
              options=[("", t("common.none")), ("jpg", "JPG"), ("png", "PNG"), ("webp", "WEBP")]),
            F("media.name_prefix", "name_prefix", "text", help_url=None),
            F("media.name_suffix", "name_suffix", "text", help_url=None),
            F("media.scan_with_defender", "scan_av", "bool", help_url=None),
        ]), t("set.tab.publish").replace("&", "&&"))

        # ---------------- Advanced
        self.tabs.addTab(_tab([
            F("bale.connect_timeout_s", "bale_connect_timeout", "float", minimum=1, maximum=120, step=1, suffix="s", help_url=None),
            F("bale.read_timeout_s", "bale_read_timeout", "float", minimum=1, maximum=600, step=1, suffix="s", help_url=None),
            F("bale.retry_count", "bale_retry_count", "int", minimum=0, maximum=10, help_url=None),
            F("bale.retry_backoff_s", "bale_retry_backoff", "float", minimum=0.1, maximum=120, step=0.5, suffix="s", help_url=None),
            F("bale.polling_interval_s", "polling_interval", "float", minimum=0.5, maximum=60, step=0.5, suffix="s", help_url=None),
            F("bale.proxy", "proxy", "text", validator=self._v_proxy, help_url=None),
            F("download.connect_timeout_s", "dl_connect_timeout", "float", minimum=1, maximum=120, step=1, suffix="s", help_url=None),
            F("download.read_timeout_s", "dl_read_timeout", "float", minimum=1, maximum=600, step=1, suffix="s", help_url=None),
            F("download.retry_count", "dl_retry_count", "int", minimum=0, maximum=20, help_url=None),
            F("download.retry_backoff_s", "dl_retry_backoff", "float", minimum=0.1, maximum=300, step=0.5, suffix="s", help_url=None),
            F("download.auto_resume", "auto_resume", "bool", help_url=None),
            F("download.auto_retry", "auto_retry", "bool", help_url=None),
            F("logging.level", "log_level", "combo", help_url=None, options=[(x, x) for x in ("DEBUG", "INFO", "WARNING", "ERROR")]),
            F("logging.retention_days", "log_retention", "int", minimum=1, maximum=3650, suffix="d", help_url=None),
            F("logging.db_retention_days", "db_retention", "int", minimum=1, maximum=3650, suffix="d", help_url=None),
            F("logging.max_db_size_mb", "db_max_size", "int", minimum=10, maximum=100000, suffix="MB", help_url=None),
            F("cleanup.interval_min", "cleanup_interval", "int", minimum=1, maximum=1440, suffix="min", help_url=None),
            F("cleanup.orphan_max_age_hours", "orphan_age", "int", minimum=1, maximum=720, suffix="h", help_url=None),
        ]), t("set.tab.advanced").replace("&", "&&"))

        # ---------------- Appearance
        self.tabs.addTab(_tab([
            F("general.language", "language", "combo", help_url=None, options=[(k, LANG_NAMES[k]) for k in LANGUAGES]),
            F("general.theme", "theme", "combo", help_url=None, options=[(k, t("theme." + k)) for k in THEMES]),
            F("general.accent", "accent", "color", help_url=None),
            F("general.show_tooltips", "show_tooltips", "bool", help_url=None),
        ]), t("set.tab.appearance").replace("&", "&&"))

        # ---------------- Backup & updates
        self.tabs.addTab(_tab(self._backup_widgets()), t("set.tab.backup").replace("&", "&&"))

        row = QHBoxLayout()
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        row.addWidget(self.msg, 1)
        rst = QPushButton(t("common.reset"))
        rst.clicked.connect(self.load)
        self.save_btn = QPushButton("💾 " + t("common.save"))
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(rst)
        row.addWidget(self.save_btn)
        self.root.addLayout(row)
        self.load()

    def _api_box(self) -> QFrame:
        t = self.t
        f = QFrame()
        f.setObjectName("panel")
        l = QVBoxLayout(f)
        self.api_key_lbl = QLabel("")
        self.api_key_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        note = QLabel(t("set.api_note"))
        note.setObjectName("hint")
        note.setWordWrap(True)
        row = QHBoxLayout()
        b1 = QPushButton(t("set.api_copy"))
        b1.clicked.connect(self._api_copy)
        b2 = QPushButton(t("set.api_regen"))
        b2.clicked.connect(self._api_regen)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        l.addWidget(QLabel(f"<b>{t('set.api_key')}</b>"))
        l.addWidget(self.api_key_lbl)
        l.addWidget(note)
        l.addLayout(row)
        return f

    def _api_state(self) -> None:
        api = self.ctx.local_api
        k = self.ctx.secrets.get("local_api_key") or ""
        self.api_key_lbl.setText((k[:4] + "•" * 12) if k else self.t("set.token_none"))
        if api.running:
            self.api_key_lbl.setText(self.api_key_lbl.text() + "   " + self.t("set.api_running", port=api.port))

    def _api_copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self.ctx.local_api.key())
        self.win.toast(self.t("set.api_key"), self.t("set.api_copied"))

    def _api_regen(self) -> None:
        if confirm(self, self.t("common.confirm"), self.t("set.api_regen_confirm"), self.t("common.yes"), self.t("common.no")):
            self.ctx.local_api.regenerate_key()
            self._api_state()

    # ------------------------------------------------------------ validators
    def _v_token(self, v):
        import re
        if v and not re.fullmatch(r"\d{4,}:[A-Za-z0-9_\-]{16,}", v):
            return self.t("err.token_format")
        return None

    def _v_uname(self, v):
        import re
        return None if not v or re.fullmatch(r"@?[A-Za-z0-9_]{3,64}", v) else self.t("err.username_format")

    def _v_dir(self, v):
        if not v:
            return self.t("err.required")
        p = Path(v)
        if p.exists() and not p.is_dir():
            return self.t("err.not_dir")
        return None

    def _v_proxy(self, v):
        return None if not v or v.lower().startswith(("http://", "https://", "socks5://", "socks5h://")) else self.t("err.proxy_format")

    # ------------------------------------------------------------ token
    def _test_token(self) -> None:
        tok = self.token.value()
        if not tok or not self.token.validate():
            self.token.set_error(self.t("err.token_format"))
            return
        self.token.set_test_result(True, self.t("common.testing"))

        def done(res, err):
            if err:
                self.token.set_test_result(False, self.t("err.token_rejected", detail=str(err)))
            else:
                self.token.set_test_result(True, self.t("set.token_ok", name=res.first_name, username=res.username))
        run_async(lambda: self.ctx.runtime.test_token(tok), done)

    def _save_token(self) -> None:
        tok = self.token.value()
        if not tok or not self.token.validate():
            return
        if not confirm(self, self.t("common.confirm"), self.t("set.confirm_token"), self.t("common.yes"), self.t("common.no")):
            return
        self.ctx.runtime.set_token(tok)
        self.token.w.clear()
        self.ctx.runtime.stop_polling()

        def done(res, err):
            if err:
                self.token.set_test_result(False, str(err))
            else:
                self.token.set_test_result(True, self.t("set.token_ok", name=res.first_name, username=res.username))
                self.ctx.start_bot()
            self._token_state()
        run_async(self.ctx.runtime.connect, done)

    def _remove_token(self) -> None:
        if confirm(self, self.t("common.confirm"), self.t("set.confirm_remove_token"), self.t("common.yes"), self.t("common.no")):
            self.ctx.runtime.clear_token()
            self._token_state()

    def _token_state(self) -> None:
        rt = self.ctx.runtime
        self.token_state.setText(self.t("set.token_saved", masked=rt.masked_token(), backend=self.ctx.secrets.backend_name)
                                 if rt.has_token() else self.t("set.token_none"))

    # ------------------------------------------------------------ load / save
    def load(self) -> None:
        s = self.ctx.sm.settings
        for path, row in self.fields.items():
            sec, key = path.split(".")
            row.set_value(getattr(getattr(s, sec), key))
        self.fields["publish.delete_after_upload"].lock(True)         # product guarantee: not switchable
        self.fields["publish.delete_after_upload"].w.setToolTip(self.t("set.locked_cleanup"))
        self._token_state()
        self._api_state()
        self._preview_caption()
        self.msg.setText("")

    def _preview_caption(self) -> None:
        ctx = {"filename": "movie.mp4", "filesize": "12.4 MB", "filetype": "video", "date": "2026-01-01", "time": "12:30",
               "source": "example.com", "duration": "3:21", "resolution": ""}
        self.caption_preview.setText(self.t("set.preview") + "\n" + render_caption(self.caption.value(), ctx))

    def _patch(self) -> dict:
        patch: dict = {}
        for path, row in self.fields.items():
            sec, key = path.split(".")
            patch.setdefault(sec, {})[key] = row.value()
        return patch

    def save(self) -> None:
        if not all(r.validate() for r in self.fields.values()):
            self.msg.setStyleSheet("color:#EF4444;")
            self.msg.setText("✖ " + self.t("set.fix_errors"))
            return
        patch = self._patch()
        errs = self.ctx.sm.validate_patch(patch)
        if errs:
            self.msg.setStyleSheet("color:#EF4444;")
            self.msg.setText("✖ " + " | ".join(errs))
            return
        cur = self.ctx.sm.settings
        changed_critical = [p for p in CRITICAL if p in self.fields
                            and getattr(getattr(cur, p.split(".")[0]), p.split(".")[1]) != patch[p.split(".")[0]][p.split(".")[1]]]
        if changed_critical:
            names = ", ".join(self.t(f"field.{self.fields[p].fid}.t") for p in changed_critical)
            if not confirm(self, self.t("common.confirm"), self.t("set.confirm_critical", names=names), self.t("common.yes"), self.t("common.no")):
                return
        lang_changed = patch["general"]["language"] != cur.general.language
        look_changed = lang_changed or patch["general"]["theme"] != cur.general.theme or patch["general"]["accent"] != cur.general.accent
        try:
            self.ctx.sm.update(patch)
        except ConfigError as e:
            self.msg.setStyleSheet("color:#EF4444;")
            self.msg.setText("✖ " + str(e))
            return
        os.makedirs(self.ctx.sm.settings.download.directory, exist_ok=True)
        self.ctx.repo.add_activity("settings_saved", "", 0, "user")
        self.msg.setStyleSheet("color:#22C55E;")
        self.msg.setText("✔ " + self.t("set.saved"))
        self.win.toast(self.t("set.title"), self.t("set.saved"))
        if look_changed:
            self.win.apply_look(rebuild=lang_changed)

    # ------------------------------------------------------------ templates
    def _edit_templates(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(self.t("set.edit_templates"))
        dlg.resize(600, 480)
        lay = QVBoxLayout(dlg)
        edits: dict[str, QPlainTextEdit] = {}
        tpls = {x["kind"]: x for x in self.ctx.repo.list_templates()}
        for kind in ("default", "image", "video", "audio", "document", "archive", "other"):
            lab = QLabel(self.t("type." + kind) if kind != "default" else self.t("set.tpl_default"))
            lab.setObjectName("h2")
            e = QPlainTextEdit(tpls[kind]["template"] if kind in tpls else "")
            e.setFixedHeight(60)
            e.setPlaceholderText(self.t("set.tpl_fallback"))
            edits[kind] = e
            lay.addWidget(lab)
            lay.addWidget(e)
        ok = QPushButton(self.t("common.save"))
        ok.setObjectName("primary")

        def save():
            for kind, e in edits.items():
                txt = e.toPlainText().strip()
                if txt:
                    old = tpls.get(kind)
                    self.ctx.repo.save_template(kind, kind, txt, True, old["id"] if old else None)
                elif kind in tpls and kind != "default":
                    self.ctx.repo.delete_template(tpls[kind]["id"])
            dlg.accept()
        ok.clicked.connect(save)
        lay.addWidget(ok)
        dlg.exec()

    # ------------------------------------------------------------ backup tab
    def _backup_widgets(self) -> list[QWidget]:
        t = self.t
        out: list[QWidget] = []

        def section(title: str, desc: str, buttons: list[tuple[str, callable]]) -> QFrame:
            f = QFrame()
            f.setObjectName("panel")
            l = QVBoxLayout(f)
            h = QLabel(f"<b>{title}</b>")
            d = QLabel(desc)
            d.setObjectName("muted")
            d.setWordWrap(True)
            l.addWidget(h)
            l.addWidget(d)
            r = QHBoxLayout()
            for text, fn in buttons:
                b = QPushButton(text)
                b.clicked.connect(fn)
                r.addWidget(b)
            r.addStretch(1)
            l.addLayout(r)
            return f
        out.append(section(t("bk.settings"), t("bk.settings_desc"), [(t("bk.export_settings"), self._export_settings), (t("bk.import_settings"), self._import_settings)]))
        out.append(section(t("bk.db"), t("bk.db_desc"), [(t("bk.backup"), self._backup), (t("bk.restore"), self._restore), (t("bk.verify"), self._verify)]))
        self.db_info = QLabel("")
        out.append(section(t("bk.health"), t("bk.health_desc"), [(t("bk.integrity"), self._integrity), (t("bk.vacuum"), self._vacuum), (t("bk.clean_now"), self._clean_now), (t("bk.open_data"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.home))))]))
        out.append(self.db_info)
        self.upd_feed = FieldRow(self.tr_, "update_feed", "text", help_url=None)
        self.upd_feed.set_value(self.ctx.sm.settings.general.update_feed_url)
        self.upd_auto = FieldRow(self.tr_, "update_auto", "bool", help_url=None)
        self.upd_auto.set_value(self.ctx.sm.settings.general.check_updates)
        self.upd_label = QLabel("")
        self.upd_label.setWordWrap(True)
        chk = QPushButton(t("upd.check"))
        chk.clicked.connect(self._check_updates)
        out += [self.upd_feed, self.upd_auto, chk, self.upd_label]
        return out

    def _pw(self, title_key: str, confirm_twice: bool = False) -> str | None:
        pw, ok = QInputDialog.getText(self, self.t(title_key), self.t("bk.password_prompt"), QLineEdit.Password)
        return pw if ok else None

    def _export_settings(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, self.t("bk.export_settings"), "settings.json", "*.json")
        if p:
            self.ctx.backup.export_settings(Path(p))
            info_box(self, self.t("bk.settings"), self.t("bk.export_done_no_token"), self.t("common.ok"))

    def _import_settings(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, self.t("bk.import_settings"), "", "*.json")
        if p and confirm(self, self.t("common.confirm"), self.t("bk.confirm_import"), self.t("common.yes"), self.t("common.no")):
            try:
                self.ctx.backup.import_settings(Path(p))
                self.load()
                self.win.apply_look(rebuild=True)
            except HubError as e:
                info_box(self, self.t("common.error"), str(e), self.t("common.ok"), True)

    def _backup(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, self.t("bk.backup"), f"bale_hub_backup_{datetime.now():%Y%m%d_%H%M}.bdhbak", "*.bdhbak")
        if not p:
            return
        pw = self._pw("bk.backup")
        if pw is None:
            return
        try:
            self.ctx.backup.backup_database(Path(p), pw or None)
            info_box(self, self.t("bk.backup"), self.t("bk.backup_done", enc=self.t("common.yes") if pw else self.t("common.no")), self.t("common.ok"))
        except HubError as e:
            info_box(self, self.t("common.error"), str(e), self.t("common.ok"), True)

    def _verify(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, self.t("bk.verify"), "", "*.bdhbak *.db")
        if not p:
            return
        pw = self._pw("bk.verify") if self.ctx.backup.is_encrypted(Path(p)) else None
        ok, msg = self.ctx.backup.verify_backup(Path(p), pw or None)
        info_box(self, self.t("bk.verify"), self.t("bk.valid") if ok else self.t("bk.invalid", msg=msg), self.t("common.ok"), not ok)

    def _restore(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, self.t("bk.restore"), "", "*.bdhbak *.db")
        if not p:
            return
        pw = self._pw("bk.restore") if self.ctx.backup.is_encrypted(Path(p)) else None
        if not confirm(self, self.t("common.confirm"), self.t("bk.confirm_restore"), self.t("common.yes"), self.t("common.no")):
            return
        try:
            self.ctx.backup.restore_database(Path(p), pw or None)
            self.win.apply_look(rebuild=True)
            info_box(self, self.t("bk.restore"), self.t("bk.restore_done"), self.t("common.ok"))
        except BackupError as e:
            info_box(self, self.t("common.error"), self.t("bk.err." + e.code) if self.t("bk.err." + e.code) != "bk.err." + e.code else str(e), self.t("common.ok"), True)

    def _integrity(self) -> None:
        ok, probs = self.ctx.db.integrity_check()
        self.db_info.setText(self.t("bk.integrity_ok" if ok else "bk.integrity_bad", size=human_size(self.ctx.db.size_bytes()), probs="; ".join(probs[:3])))

    def _vacuum(self) -> None:
        self.ctx.db.vacuum()
        self._integrity()

    def _clean_now(self) -> None:
        r = self.ctx.scheduler.run_once()
        self.win.toast(self.t("bk.clean_now"), self.t("bk.cleaned", freed=human_size(r["freed"]) or "0 B", files=r["files"]))

    def _check_updates(self) -> None:
        from app.services.update_service import check_for_updates
        feed = self.upd_feed.value()
        self.ctx.sm.update({"general": {"update_feed_url": feed, "check_updates": self.upd_auto.value()}})
        self.upd_label.setText(self.t("common.testing"))

        def done(res, err):
            if res.error:
                self.upd_label.setText(self.t("upd.error", err=self.t("upd.no_feed") if res.error == "no_feed" else res.error))
            elif res.available:
                self.upd_label.setText(self.t("upd.available", v=res.latest, notes=res.notes) + (("\n⚠ " + self.t("upd.security")) if res.security else "") + "\n" + self.t("upd.manual"))
            else:
                self.upd_label.setText(self.t("upd.latest", v=res.current))
        run_async(lambda: check_for_updates(feed), done)
