from __future__ import annotations

from datetime import datetime, time as dtime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget)

from app.services import report_service
from app.services.caption import human_size
from app.ui.components.widgets import info_box
from app.ui.pages.base import Page

TABS = {
    "downloads": ["created_at", "status", "filename", "size_total", "category", "source", "requester_id", "result", "error_code", "cleanup_status"],
    "publishes": ["sent_at", "channel_label", "status", "method", "filename", "size", "error"],
    "errors": ["ts", "component", "level", "message"],
    "security": ["ts", "actor_id", "action", "detail"],
    "users": ["ts", "actor_id", "action", "detail"],
    "cleanup": ["ts", "job_id", "reason", "files_removed", "bytes_freed", "status", "note"],
}
SIZE_COLS = {"size_total", "size", "bytes_freed"}


class LogsPage(Page):
    title_key = "nav.logs"

    def __init__(self, win):
        super().__init__(win)
        self.header(self.t("logs.title"), self.t("logs.sub"))
        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t("logs.search_ph"))
        self.use_from, self.use_to = QCheckBox(self.t("logs.from")), QCheckBox(self.t("logs.to"))
        self.d_from, self.d_to = QDateEdit(QDate.currentDate().addDays(-7)), QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
        self.status = QComboBox()
        self.status.addItem(self.t("common.all"), None)
        for s in ("completed", "failed", "cancelled", "waiting", "downloading", "uploading", "paused"):
            self.status.addItem(self.t("status." + s), s)
        self.chan = QComboBox()
        for w in (self.search, self.use_from, self.d_from, self.use_to, self.d_to, self.status, self.chan):
            f.addWidget(w, 1 if w is self.search else 0)
        go = QPushButton("🔎 " + self.t("logs.apply"))
        go.setObjectName("primary")
        go.clicked.connect(self.refresh)
        f.addWidget(go)
        self.root.addLayout(f)
        self.search.returnPressed.connect(self.refresh)
        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        for key, cols in TABS.items():
            tb = QTableWidget(0, len(cols))
            tb.setHorizontalHeaderLabels([self.t("lc." + c) for c in cols])
            tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            tb.horizontalHeader().setStretchLastSection(True)
            tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tb.setAlternatingRowColors(True)
            tb.verticalHeader().setVisible(False)
            self.tables[key] = tb
            self.tabs.addTab(tb, self.t("logs.tab." + key))
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        self.root.addWidget(self.tabs, 1)
        bar = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("muted")
        bar.addWidget(self.count, 1)
        for key, fn in (("logs.export_csv", lambda: self.export("csv")), ("logs.export_json", lambda: self.export("json")),
                        ("logs.print", self.print_)):
            b = QPushButton(self.t(key))
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.root.addLayout(bar)
        self.rows_cache: dict[str, list[dict]] = {}
        self._reload_channels()
        self.refresh()

    def _reload_channels(self) -> None:
        self.chan.clear()
        self.chan.addItem(self.t("logs.all_channels"), None)
        for c in self.ctx.repo.list_channels():
            self.chan.addItem(c["title"] or c["chat_id"], c["id"])

    def _range(self):
        a = datetime.combine(self.d_from.date().toPython(), dtime.min) if self.use_from.isChecked() else None
        b = datetime.combine(self.d_to.date().toPython(), dtime.max) if self.use_to.isChecked() else None
        return a, b

    def _fetch(self, key: str) -> list[dict]:
        r, since, until = self.ctx.repo, *self._range()
        q = self.search.text().strip() or None
        st, ch = self.status.currentData(), self.chan.currentData()
        if key == "downloads":
            return r.list_jobs(statuses=[st] if st else None, search=q, since=since, until=until, channel_id=ch, limit=2000)
        if key == "publishes":
            ps = {"completed": "sent", "failed": "failed"}.get(st) if st else None
            return r.list_publishes(status=ps, search=q, since=since, until=until, channel_id=ch, limit=2000)
        if key == "errors":
            return r.list_errors(search=q, since=since, until=until, limit=2000)
        if key == "security":
            return r.list_activity("security", None, q, since, until, 2000)
        if key == "users":
            return r.list_activity("user", None, q, since, until, 2000)
        return r.list_cleanups(since=since, limit=2000)

    def refresh(self) -> None:
        key = list(TABS)[self.tabs.currentIndex()]
        rows = self._fetch(key)
        self.rows_cache[key] = rows
        cols = TABS[key]
        tb = self.tables[key]
        tb.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, c in enumerate(cols):
                v = r.get(c)
                if c in SIZE_COLS:
                    v = "\u200e" + (human_size(v) or "0 B")
                elif c == "status" and key == "downloads":
                    v = self.t("status." + str(v))
                elif c in ("created_at", "sent_at", "ts") and v:
                    v = f"{v:%Y-%m-%d %H:%M:%S}"
                tb.setItem(i, j, QTableWidgetItem("" if v is None else str(v)))
        self.count.setText(self.t("logs.count", n=len(rows)))

    def _current(self):
        key = list(TABS)[self.tabs.currentIndex()]
        return key, self.rows_cache.get(key, []), TABS[key]

    def export(self, fmt: str) -> None:
        key, rows, cols = self._current()
        path, _ = QFileDialog.getSaveFileName(self, self.t("logs.export_" + fmt), f"{key}.{fmt}", f"*.{fmt}")
        if not path:
            return
        try:
            (report_service.export_csv if fmt == "csv" else report_service.export_json)(rows, path, cols)
            self.win.toast(self.t("logs.title"), self.t("logs.exported", path=path))
        except OSError as e:
            info_box(self, self.t("common.error"), str(e), self.t("common.ok"), True)

    def print_(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        key, rows, cols = self._current()
        doc = QTextDocument()
        doc.setHtml(report_service.to_html(self.t("logs.tab." + key), rows, cols, self.ctx.tr.is_rtl))
        pr = QPrinter()
        dlg = QPrintDialog(pr, self)
        if dlg.exec():
            doc.print_(pr)
