from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.security.access_control import Role
from app.ui.components.widgets import FieldRow, confirm, info_box
from app.ui.pages.base import Page


class UserDialog(QDialog):
    def __init__(self, win, user: dict | None = None):
        super().__init__(win)
        self.ctx, self.user = win.ctx, user
        t = self.t = self.ctx.tr
        self.setWindowTitle(t("users.edit" if user else "users.add"))
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        self.f_id = FieldRow(t, "user_id", "text", validator=self._v_id, help_url=None)
        self.f_name = FieldRow(t, "user_name", "text", help_url=None)
        self.f_role = FieldRow(t, "user_role", "combo", options=[(r.name, t("role." + r.name)) for r in
                                                                 sorted(Role, reverse=True)], help_url=None)
        self.f_quota = FieldRow(t, "user_quota", "int", minimum=0, maximum=1_000_000, suffix="MB", help_url=None)
        for f in (self.f_id, self.f_name, self.f_role, self.f_quota):
            lay.addWidget(f)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton(t("common.cancel"))
        c.clicked.connect(self.reject)
        ok = QPushButton(t("common.save"))
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)
        if user:
            self.f_id.set_value(str(user["user_id"]))
            self.f_id.lock(True)
            self.f_name.set_value(user["display_name"])
            self.f_role.set_value(user["role"])
            self.f_quota.set_value(user["daily_quota_mb"])
        else:
            self.f_role.set_value("OPERATOR")
            self.f_quota.set_value(0)

    def _v_id(self, v) -> str | None:
        v = (v or "").strip()
        return None if v.isdigit() and int(v) > 0 else self.t("err.numeric_id")

    def _save(self) -> None:
        if not self.f_id.validate():
            return
        uid = int(self.f_id.value())
        role = self.f_role.value()
        if role == "SUPER_ADMIN" and self.user and self.user["role"] != "SUPER_ADMIN":
            if not confirm(self, self.t("common.confirm"), self.t("users.confirm_super"), self.t("common.yes"), self.t("common.no")):
                return
        self.ctx.repo.add_user(uid, self.f_name.value(), role, self.f_quota.value())
        self.ctx.repo.update_user(uid, daily_quota_mb=self.f_quota.value())
        self.ctx.repo.add_activity("user_saved", f"{uid} as {role}", 0, "user")
        self.accept()


class UsersPage(Page):
    title_key = "nav.users"

    def __init__(self, win):
        super().__init__(win)
        self.header(self.t("users.title"), self.t("users.sub"))
        bar = QHBoxLayout()
        for key, fn, name in (("users.add", self.add, "primary"), ("users.edit", self.edit, None),
                              ("users.block", self.block, None), ("users.remove", self.remove, "danger")):
            b = QPushButton(self.t(key))
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.root.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([self.t(k) for k in ("users.col.id", "users.col.name", "users.col.role", "col.status", "users.col.quota")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._activity)
        self.root.addWidget(self.table, 3)
        note = QLabel(self.t("users.note"))
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.root.addWidget(note)
        lbl = QLabel(self.t("users.activity"))
        lbl.setObjectName("h2")
        self.root.addWidget(lbl)
        self.act = QListWidget()
        self.root.addWidget(self.act, 2)
        self.refresh()

    def _sel(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return self.ctx.repo.get_user(int(it.text())) if it else None

    def refresh(self) -> None:
        keep = (self._sel() or {}).get("user_id")
        users = self.ctx.repo.list_users()
        self.table.setRowCount(len(users))
        for i, u in enumerate(users):
            vals = [str(u["user_id"]), u["display_name"] or "—", self.t("role." + u["role"]),
                    self.t("users.blocked") if u["blocked"] else self.t("users.active"),
                    f"{u['daily_quota_mb']} MB" if u["daily_quota_mb"] else self.t("users.default_quota")]
            for j, v in enumerate(vals):
                self.table.setItem(i, j, QTableWidgetItem(v))
            if u["user_id"] == keep:
                self.table.selectRow(i)
        self._activity()

    def _activity(self) -> None:
        self.act.clear()
        u = self._sel()
        rows = self.ctx.repo.list_activity(actor_id=u["user_id"], limit=100) if u else self.ctx.repo.list_activity(limit=60)
        for a in rows:
            self.act.addItem(f"{a['ts']:%m-%d %H:%M}  [{a['category']}]  {a['action']}  {a['detail'][:80]}")

    def add(self) -> None:
        if UserDialog(self.win).exec():
            self.refresh()

    def edit(self) -> None:
        u = self._sel()
        if u and UserDialog(self.win, u).exec():
            self.refresh()

    def _last_super(self, u: dict) -> bool:
        supers = [x for x in self.ctx.repo.list_users() if x["role"] == "SUPER_ADMIN" and not x["blocked"]]
        return u["role"] == "SUPER_ADMIN" and len(supers) <= 1

    def block(self) -> None:
        u = self._sel()
        if not u:
            return
        if self._last_super(u) and not u["blocked"]:
            info_box(self, self.t("common.warning"), self.t("users.last_super"), self.t("common.ok"), True)
            return
        self.ctx.repo.update_user(u["user_id"], blocked=not u["blocked"])
        self.ctx.repo.add_activity("unblock" if u["blocked"] else "block", str(u["user_id"]), 0, "user")
        self.refresh()

    def remove(self) -> None:
        u = self._sel()
        if not u:
            return
        if self._last_super(u):
            info_box(self, self.t("common.warning"), self.t("users.last_super"), self.t("common.ok"), True)
            return
        if confirm(self, self.t("common.confirm"), self.t("users.confirm_remove", id=u["user_id"]), self.t("common.yes"), self.t("common.no")):
            self.ctx.repo.remove_user(u["user_id"])
            self.ctx.repo.add_activity("user_removed", str(u["user_id"]), 0, "user")
            self.refresh()
