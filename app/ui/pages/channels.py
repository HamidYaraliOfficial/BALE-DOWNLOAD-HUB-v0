from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.core.constants import CATEGORIES
from app.core.exceptions import HubError
from app.services.caption import human_size
from app.ui.components.async_util import run_async
from app.ui.components.widgets import FieldRow, confirm, info_box
from app.ui.pages.base import Page

STATUS_COLOR = {"ok": "#22C55E", "error": "#EF4444", "unverified": "#F59E0B"}


class ChannelDialog(QDialog):
    def __init__(self, win, channel: dict | None = None):
        super().__init__(win)
        self.win, self.ctx, self.ch = win, win.ctx, channel
        self.t = self.ctx.tr
        self.setWindowTitle(self.t("chan.edit" if channel else "chan.add"))
        self.resize(640, 640)
        self.check = None
        lay = QVBoxLayout(self)
        self.f_id = FieldRow(self.t, "channel_id", "text", on_test=self._test, validator=self._v_id)
        self.f_title = FieldRow(self.t, "channel_title", "text", help_url=None)
        self.f_cats = FieldRow(self.t, "channel_categories", "multicheck", help_url=None)
        for f in (self.f_id, self.f_title, self.f_cats):
            lay.addWidget(f)
        self.f_default = FieldRow(self.t, "channel_default", "bool", help_url=None)
        lay.addWidget(self.f_default)
        self.confirm = QCheckBox(self.t("chan.confirm_authorized"))
        lay.addWidget(self.confirm)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton(self.t("common.cancel"))
        c.clicked.connect(self.reject)
        self.ok = QPushButton(self.t("common.save"))
        self.ok.setObjectName("primary")
        self.ok.clicked.connect(self._save)
        row.addWidget(c)
        row.addWidget(self.ok)
        lay.addLayout(row)
        if channel:
            self.f_id.set_value(channel["chat_id"])
            self.f_id.lock(True)
            self.f_title.set_value(channel["title"])
            self.f_cats.set_value(channel["categories"])
            self.f_default.set_value(channel["is_default"])
            self.confirm.setChecked(True)
        else:
            self.f_cats.set_value([])

    def _v_id(self, v) -> str | None:
        v = (v or "").strip()
        if not v:
            return self.t("err.required")
        if not (v.lstrip("-").isdigit() or v.lstrip("@").replace("_", "").isalnum()):
            return self.t("err.channel_format")
        return None

    def _test(self) -> None:
        if not self.f_id.validate():
            return
        if not confirm(self, self.t("chan.probe_title"), self.t("chan.probe_text"), self.t("common.yes"), self.t("common.no")):
            return
        self.f_id.set_test_result(True, self.t("common.testing"))
        cid = self.f_id.value()
        run_async(lambda: self.ctx.runtime.adapter().check_channel(cid, probe_post=True), self._tested)

    def _tested(self, res, err) -> None:
        if err:
            self.f_id.set_test_result(False, getattr(err, "args", [str(err)])[0] if str(err) else type(err).__name__)
            self.check = None
            return
        self.check = res
        if res.ok and res.can_post:
            self.f_id.set_test_result(True, self.t("chan.test_ok", title=res.title or "-"))
            if not self.f_title.value():
                self.f_title.set_value(res.title)
        else:
            self.f_id.set_test_result(False, self.t("chan.test_fail", detail=res.detail or ""))

    def _save(self) -> None:
        if not self.f_id.validate():
            return
        if not self.confirm.isChecked():
            info_box(self, self.t("common.warning"), self.t("chan.need_confirm"), self.t("common.ok"), True)
            return
        status = "ok" if (self.check and self.check.ok and self.check.can_post) else "unverified"
        try:
            cid = self.f_id.value()
            if self.ch:
                self.ctx.repo.update_channel(self.ch["id"], title=self.f_title.value(), categories=self.f_cats.value(),
                                             is_default=self.f_default.value() or self.ch["is_default"])
            else:
                ch = self.ctx.repo.add_channel(cid, self.f_title.value() or (self.check.title if self.check else ""),
                                               cid.lstrip("@") if not cid.lstrip("-").isdigit() else "",
                                               self.f_default.value(), self.f_cats.value())
                self.ctx.repo.update_channel(ch["id"], status=status, last_checked=datetime.utcnow(),
                                             status_detail="" if status == "ok" else "not tested")
            self.ctx.repo.add_activity("channel_saved", cid, 0, "user")
            self.accept()
        except ValueError:
            info_box(self, self.t("common.error"), self.t("chan.exists"), self.t("common.ok"), True)


class ChannelsPage(Page):
    title_key = "nav.channels"

    def __init__(self, win):
        super().__init__(win)
        self.header(self.t("chan.title"), self.t("chan.sub"))
        bar = QHBoxLayout()
        for key, fn, name in (("chan.add", self.add, "primary"), ("chan.edit", self.edit, None),
                              ("chan.delete", self.delete, "danger"), ("chan.set_default", self.set_default, None),
                              ("chan.toggle", self.toggle, None), ("chan.test", self.test, None)):
            b = QPushButton(self.t(key))
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.root.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([self.t(k) for k in ("col.default", "chan.col.title", "chan.col.id", "col.status",
                                                                   "chan.col.enabled", "chan.col.routes", "chan.col.checked")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_results)
        self.root.addWidget(self.table, 3)
        lbl = QLabel(self.t("chan.last_results"))
        lbl.setObjectName("h2")
        self.root.addWidget(lbl)
        self.res = QTableWidget(0, 5)
        self.res.setHorizontalHeaderLabels([self.t(k) for k in ("col.time", "col.status", "pub.method", "col.file", "col.info")])
        self.res.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.res.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.res.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.res.verticalHeader().setVisible(False)
        self.root.addWidget(self.res, 2)
        self.refresh()

    def _sel(self) -> dict | None:
        r = self.table.currentRow()
        it = self.table.item(r, 1) if r >= 0 else None
        return self.ctx.repo.get_channel(it.data(Qt.UserRole)) if it else None

    def refresh(self) -> None:
        keep = (self._sel() or {}).get("id")
        chans = self.ctx.repo.list_channels()
        self.table.setRowCount(len(chans))
        for i, c in enumerate(chans):
            vals = ["★" if c["is_default"] else "", c["title"] or "—", c["chat_id"], self.t("chan.status." + c["status"]),
                    "✔" if c["enabled"] else "✖", ", ".join(self.t("type." + k) for k in c["categories"]) or self.t("chan.all_types"),
                    f"{c['last_checked']:%Y-%m-%d %H:%M}" if c["last_checked"] else "—"]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 3:
                    from PySide6.QtGui import QColor
                    it.setForeground(QColor(STATUS_COLOR.get(c["status"], "#94A3B8")))
                    it.setToolTip(c["status_detail"] or "")
                if j == 1:
                    it.setData(Qt.UserRole, c["id"])
                self.table.setItem(i, j, it)
            if c["id"] == keep:
                self.table.selectRow(i)
        self._show_results()

    def _show_results(self) -> None:
        ch = self._sel()
        rows = self.ctx.repo.list_publishes(channel_id=ch["id"], limit=20) if ch else []
        self.res.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [f"{r['sent_at']:%m-%d %H:%M}", self.t("pubstatus." + r["status"]), r["method"] or "—", r["filename"] or "—", r["error"] or ""]
            for j, v in enumerate(vals):
                self.res.setItem(i, j, QTableWidgetItem(v))

    def add(self) -> None:
        if not self.ctx.runtime.has_token():
            info_box(self, self.t("common.warning"), self.t("chan.need_token"), self.t("common.ok"), True)
            return
        if ChannelDialog(self.win).exec():
            self.refresh()

    def edit(self) -> None:
        ch = self._sel()
        if ch and ChannelDialog(self.win, ch).exec():
            self.refresh()

    def delete(self) -> None:
        ch = self._sel()
        if ch and confirm(self, self.t("common.confirm"), self.t("chan.confirm_delete", name=ch["title"] or ch["chat_id"]),
                          self.t("common.yes"), self.t("common.no")):
            self.ctx.repo.delete_channel(ch["id"])
            self.ctx.repo.add_activity("channel_deleted", ch["chat_id"], 0, "user")
            self.refresh()

    def set_default(self) -> None:
        ch = self._sel()
        if ch:
            self.ctx.repo.update_channel(ch["id"], is_default=True)
            self.refresh()

    def toggle(self) -> None:
        ch = self._sel()
        if ch:
            self.ctx.repo.update_channel(ch["id"], enabled=not ch["enabled"])
            self.refresh()

    def test(self) -> None:
        ch = self._sel()
        if not ch:
            return
        if not confirm(self, self.t("chan.probe_title"), self.t("chan.probe_text"), self.t("common.yes"), self.t("common.no")):
            return

        def done(res, err):
            if err:
                self.ctx.repo.update_channel(ch["id"], status="error", status_detail=str(err)[:300], last_checked=datetime.utcnow())
                self.win.toast(self.t("chan.test"), str(err), True)
            else:
                ok = res.ok and res.can_post
                self.ctx.repo.update_channel(ch["id"], status="ok" if ok else "error", status_detail=res.detail,
                                             last_checked=datetime.utcnow(), title=ch["title"] or res.title)
                self.win.toast(self.t("chan.test"), self.t("chan.test_ok", title=res.title) if ok else self.t("chan.test_fail", detail=res.detail), not ok)
            self.refresh()

        run_async(lambda: self.ctx.runtime.adapter().check_channel(ch["chat_id"], True), done)
