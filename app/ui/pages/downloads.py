from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QDateTime, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout)

from app.core.constants import ACTIVE_STATUSES, JobStatus
from app.downloader.validators import dedupe_links, extract_links, read_links_file
from app.services.caption import human_size
from app.ui.components.async_util import run_async
from app.ui.components.widgets import confirm, info_box
from app.ui.pages.base import Page, fmt_eta, fmt_speed
from app.ui.theme import STATUS_COLORS

LRM = "\u200e"
COLS = ["file", "status", "size", "progress", "speed", "eta", "priority", "source", "info"]


class AddLinksDialog(QDialog):
    """Paste/import links -> analyse (probe) -> review file info -> confirm. Nothing is queued before the OK."""

    def __init__(self, win, initial_text: str = ""):
        super().__init__(win)
        self.win, self.ctx = win, win.ctx
        self.t = self.ctx.tr
        self.setWindowTitle(self.t("add.title"))
        self.resize(900, 640)
        self.results: list = []
        lay = QVBoxLayout(self)
        hint = QLabel(self.t("add.hint"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("https://example.com/file.zip\nhttps://example.com/video.mp4")
        self.text.setPlainText(initial_text)
        self.text.setFixedHeight(120)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        for key, fn in (("add.paste", self._paste), ("add.import_txt", lambda: self._import("txt")),
                        ("add.import_csv", lambda: self._import("csv"))):
            b = QPushButton(self.t(key))
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.analyze_btn = QPushButton("🔍 " + self.t("add.analyze"))
        self.analyze_btn.setObjectName("primary")
        self.analyze_btn.clicked.connect(self._analyze)
        row.addWidget(self.analyze_btn)
        lay.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", self.t("col.file"), self.t("col.size"), self.t("col.type"),
                                              self.t("col.source"), self.t("col.info")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(4, 260)
        self.table.setMinimumHeight(220)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table, 1)
        opts = QFormLayout()
        self.chan_box = QComboBox()
        self.chan_box.addItem(self.t("add.default_channel"), None)
        for c in self.ctx.repo.list_channels(enabled_only=True):
            self.chan_box.addItem(c["title"] or c["chat_id"], c["id"])
        self.multi = QCheckBox(self.t("add.all_channels"))
        self.priority = QSpinBox()
        self.priority.setRange(-10, 10)
        self.schedule = QCheckBox(self.t("add.schedule"))
        self.when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.when.setCalendarPopup(True)
        self.when.setEnabled(False)
        self.schedule.toggled.connect(self.when.setEnabled)
        self.caption = QLineEdit()
        self.caption.setPlaceholderText(self.t("add.caption_ph"))
        opts.addRow(self.t("add.destination"), self.chan_box)
        opts.addRow("", self.multi)
        opts.addRow(self.t("col.priority"), self.priority)
        opts.addRow(self.schedule, self.when)
        opts.addRow(self.t("add.caption"), self.caption)
        lay.addLayout(opts)
        sched_note = QLabel(self.t("add.schedule_note"))
        sched_note.setObjectName("hint")
        lay.addWidget(sched_note)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(self.t("common.cancel"))
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton(self.t("add.confirm"))
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._confirm)
        btns.addWidget(cancel)
        btns.addWidget(self.ok_btn)
        lay.addLayout(btns)
        self.added: list = []

    def _paste(self) -> None:
        self.text.appendPlainText(QGuiApplication.clipboard().text())

    def _import(self, kind: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.t("add.import_" + kind), "", f"*.{kind}")
        if path:
            try:
                self.text.appendPlainText("\n".join(read_links_file(path)))
            except Exception as e:
                info_box(self, self.t("common.error"), str(e), self.t("common.ok"), True)

    def _analyze(self) -> None:
        uniq, dups = dedupe_links(extract_links(self.text.toPlainText()))
        if not uniq:
            self.status.setText(self.t("add.none_found"))
            return
        self.analyze_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.status.setText(self.t("add.analyzing", n=len(uniq)) + (f"  ({self.t('add.dups', n=len(dups))})" if dups else ""))
        eng = self.ctx.downloads

        def work():
            out = []
            for u in uniq:
                try:
                    out.append((u, eng.preview(u), None))
                except Exception as e:
                    out.append((u, None, e))
            return out

        run_async(work, self._analyzed)

    def _analyzed(self, res, err) -> None:
        self.analyze_btn.setEnabled(True)
        if err:
            self.status.setText(str(err))
            return
        self.results = res
        self.table.setRowCount(len(res))
        any_ok = False
        for i, (url, probe, e) in enumerate(res):
            ok = bool(probe and probe.supported)
            cb = QTableWidgetItem()
            cb.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled if ok else Qt.NoItemFlags)
            cb.setCheckState(Qt.Checked if ok else Qt.Unchecked)
            self.table.setItem(i, 0, cb)
            if ok:
                any_ok = True
                vals = [probe.filename, human_size(probe.size) or self.t("common.unknown"), self.t(f"type.{probe.category}"),
                        url, ("✔ " + (self.t("add.resumable") if probe.resumable else self.t("add.ok")))]
            else:
                code = (e.code if e is not None and hasattr(e, "code") else (probe.reason_code if probe else "probe_failed"))
                vals = ["—", human_size(probe.size) if probe and probe.size else "—", "—", url, "✖ " + self.error_text(code)]
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(str(v))
                it.setToolTip(str(v))
                if not ok:
                    it.setForeground(Qt.red if c == 5 else it.foreground())
                self.table.setItem(i, c, it)
        self.ok_btn.setEnabled(any_ok)
        self.status.setText(self.t("add.analyzed", ok=sum(1 for _u, p, _e in res if p and p.supported), n=len(res)))

    def error_text(self, code: str) -> str:
        k = "error." + code
        return self.t(k) if self.t(k) != k else code

    def _confirm(self) -> None:
        sched = None
        if self.schedule.isChecked():
            sched = self.when.dateTime().toPython().astimezone(timezone.utc).replace(tzinfo=None)
        dest = [self.chan_box.currentData()] if self.chan_box.currentData() else []
        if self.multi.isChecked():
            dest = [c["id"] for c in self.ctx.repo.list_channels(enabled_only=True)]
        n_ok, problems = 0, []
        for i, (url, probe, _e) in enumerate(self.results):
            if not (probe and probe.supported) or self.table.item(i, 0).checkState() != Qt.Checked:
                continue
            r = self.ctx.downloads.add_job(url, "desktop", 0, dest or None, self.priority.value(), sched,
                                           self.caption.text().strip() or None, probe)
            if r.ok:
                n_ok += 1
            else:
                problems.append(f"{url[:60]}: {self.error_text(r.code)}")
        self.added = [n_ok, problems]
        if problems:
            info_box(self, self.t("common.warning"), "\n".join(problems), self.t("common.ok"), True)
        self.accept()


class PreviewDialog(QDialog):
    """Shown before publishing when auto-publish is off: file info + thumbnail + Publish/Discard."""

    def __init__(self, win, job: dict):
        super().__init__(win)
        self.t = win.ctx.tr
        self.setWindowTitle(self.t("preview.title"))
        self.resize(520, 520)
        lay = QVBoxLayout(self)
        path = win.ctx.downloads.job_file(job)
        meta = job["meta"].get("media") or {}
        img = QLabel(alignment=Qt.AlignCenter)
        pm = None
        if path and job["category"] == "image":
            pm = QPixmap(str(path))
        elif path and job["category"] == "video":
            from app.media.thumbnails import make_thumbnail
            tp = make_thumbnail(path, "video", path.parent / ".thumbs")
            pm = QPixmap(str(tp)) if tp else None
        if pm and not pm.isNull():
            img.setPixmap(pm.scaled(440, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            img.setText("📄")
            img.setStyleSheet("font-size: 64pt;")
        lay.addWidget(img)
        info = QTextEdit(readOnly=True)
        lines = [f"{self.t('col.file')}: {job['filename']}", f"{self.t('col.size')}: {human_size(job['size_total'])}",
                 f"{self.t('col.type')}: {self.t('type.' + (job['category'] or 'other'))}"]
        if meta.get("resolution"):
            lines.append(f"{self.t('preview.resolution')}: {meta['resolution']}")
        if meta.get("duration"):
            lines.append(f"{self.t('preview.duration')}: {meta['duration']:.0f}s")
        lines.append(f"SHA-256: {job['sha256']}")
        caption = win.ctx.publishing.build_caption(job, job["filename"] or "", job["size_total"], job["category"] or "other",
                                                   type("I", (), {"duration": meta.get("duration"), "resolution": meta.get("resolution")}))
        lines += ["", self.t("preview.caption") + ":", caption]
        info.setPlainText("\n".join(lines))
        lay.addWidget(info, 1)
        row = QHBoxLayout()
        no = QPushButton(self.t("preview.discard"))
        no.setObjectName("danger")
        no.clicked.connect(self.reject)
        yes = QPushButton("⬆ " + self.t("preview.publish"))
        yes.setObjectName("primary")
        yes.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)


class DownloadsPage(Page):
    title_key = "nav.downloads"

    def __init__(self, win):
        super().__init__(win)
        self.live: dict[str, tuple] = {}
        self.rows: dict[str, int] = {}
        hr = self.header(self.t("dl.title"), self.t("dl.sub"))
        self.queue_btn = QPushButton()
        self.queue_btn.clicked.connect(self._toggle_queue)
        hr.addWidget(self.queue_btn)

        bar = QHBoxLayout()
        bar2 = QHBoxLayout()

        def btn(key, fn, name=None, tip=None, row=None):
            b = QPushButton(self.t(key))
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            if tip:
                b.setToolTip(self.t(tip))
            (row or bar2).addWidget(b)
            return b
        btn("dl.add", self.add_links, "primary", row=bar)
        btn("dl.paste", self.paste_links, tip="dl.paste_tip", row=bar)
        btn("dl.open_folder", self.open_folder, row=bar)
        bar.addStretch(1)
        btn("dl.pause", lambda: self._each(self.ctx.downloads.pause))
        btn("dl.resume", lambda: self._each(self.ctx.downloads.resume))
        btn("dl.cancel", self._cancel, "danger")
        btn("dl.retry", lambda: self._each(self.ctx.downloads.retry))
        btn("dl.up", lambda: self._move(1))
        btn("dl.down", lambda: self._move(-1))
        btn("dl.approve", self._approve)
        bar2.addStretch(1)
        self.filter = QComboBox()
        self.filter.addItem(self.t("common.all"), None)
        for s_ in JobStatus:
            self.filter.addItem(self.t("status." + s_.value), s_.value)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t("common.search"))
        self.search.setMinimumWidth(180)
        self.search.textChanged.connect(self.refresh)
        bar2.addWidget(self.filter)
        bar2.addWidget(self.search)
        self.root.addLayout(bar)
        self.root.addLayout(bar2)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([self.t("col." + c) for c in COLS])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(8, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(3, 170)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda _i: self._approve())
        self.root.addWidget(self.table, 1)
        self.footer = QLabel("")
        self.footer.setObjectName("muted")
        self.root.addWidget(self.footer)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.isVisible() and self.refresh())
        self.timer.start(900)
        self.refresh()

    # ------------------------------------------------------------ actions
    def selected_ids(self) -> list[str]:
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it:
                ids.append(it.data(Qt.UserRole))
        return ids

    def _each(self, fn) -> None:
        for jid in self.selected_ids():
            fn(jid)
        self.refresh()

    def _cancel(self) -> None:
        ids = self.selected_ids()
        if ids and confirm(self, self.t("common.confirm"), self.t("dl.confirm_cancel", n=len(ids)),
                           self.t("common.yes"), self.t("common.no")):
            for jid in ids:
                self.ctx.downloads.cancel(jid)
            self.refresh()

    def _move(self, d: int) -> None:
        for jid in self.selected_ids()[:1]:
            self.ctx.downloads.queue.move(jid, d)
        self.refresh()

    def _toggle_queue(self) -> None:
        q = self.ctx.downloads.queue
        if q.paused:
            q.resume_queue()
        else:
            q.pause_queue("user")
        self.refresh()

    def _approve(self) -> None:
        for jid in self.selected_ids()[:1]:
            j = self.ctx.repo.get_job(jid)
            if j and j.get("awaiting_approval"):
                if PreviewDialog(self.win, j).exec() == QDialog.Accepted:
                    self.ctx.downloads.approve(jid)
                else:
                    if confirm(self, self.t("common.confirm"), self.t("preview.confirm_discard"),
                               self.t("common.yes"), self.t("common.no")):
                        self.ctx.downloads.cancel(jid)
        self.refresh()

    def add_links(self, text: str = "") -> None:
        dlg = AddLinksDialog(self.win, text)
        if dlg.exec() == QDialog.Accepted and dlg.added:
            self.win.toast(self.t("dl.title"), self.t("add.queued_n", n=dlg.added[0]))
        self.refresh()

    def paste_links(self) -> None:
        txt = QGuiApplication.clipboard().text()
        if not extract_links(txt):
            self.win.toast(self.t("dl.title"), self.t("add.none_found"), True)
            return
        self.add_links(txt)

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.cleanup.base_dir())))

    def _menu(self, pos) -> None:
        m = QMenu(self)
        for key, fn in (("dl.pause", lambda: self._each(self.ctx.downloads.pause)),
                        ("dl.resume", lambda: self._each(self.ctx.downloads.resume)),
                        ("dl.retry", lambda: self._each(self.ctx.downloads.retry)),
                        ("dl.cancel", self._cancel), ("dl.approve", self._approve)):
            m.addAction(self.t(key), fn)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ live data
    def on_event(self, name: str, p: dict) -> None:
        if name == "job.progress":
            self.live[p["job_id"]] = (p["done"], p["total"], p["speed"], p["phase"])
        elif name in ("job.added", "job.updated", "job.finished", "queue.state"):
            if self.isVisible():
                self.refresh()

    def refresh(self) -> None:
        q = self.ctx.downloads.queue
        self.queue_btn.setText(("▶ " + self.t("dl.resume_queue")) if q.paused else ("⏸ " + self.t("dl.pause_queue")))
        self.queue_btn.setObjectName("primary" if q.paused else "")
        self.queue_btn.style().unpolish(self.queue_btn)
        self.queue_btn.style().polish(self.queue_btn)
        jobs = self.ctx.repo.list_jobs(statuses=[self.filter.currentData()] if self.filter.currentData() else None,
                                       search=self.search.text().strip() or None, limit=300)
        # keep live (queued/active) jobs ahead of finished ones
        order = {"downloading": 0, "uploading": 0, "processing": 0, "validating": 0, "cleanup": 0, "paused": 1, "waiting": 1}
        jobs.sort(key=lambda j: order.get(j["status"], 2))
        sel = set(self.selected_ids())
        self.table.setUpdatesEnabled(False)
        ids = [j["id"] for j in jobs]
        if list(self.rows) != ids:
            self.table.setRowCount(len(jobs))
            self.rows = {jid: i for i, jid in enumerate(ids)}
            for i in range(len(jobs)):
                for c in range(len(COLS)):
                    if c == 3 and self.table.cellWidget(i, 3) is None:
                        pb = QProgressBar()
                        pb.setRange(0, 1000)
                        self.table.setCellWidget(i, 3, pb)
                    elif c != 3 and self.table.item(i, c) is None:
                        self.table.setItem(i, c, QTableWidgetItem())
        for i, j in enumerate(jobs):
            self._fill(i, j)
        self.table.setUpdatesEnabled(True)
        for jid in sel:
            if jid in self.rows:
                self.table.selectRow(self.rows[jid])
        st = self.ctx.repo.count_by_status()
        self.footer.setText(self.t("dl.footer", active=sum(st.get(s, 0) for s in ACTIVE_STATUSES), waiting=st.get("waiting", 0),
                                   paused=st.get("paused", 0)) + (f"   ⏸ {self.t('dl.queue_paused_note', reason=q.pause_reason)}" if q.paused else ""))

    def _fill(self, i: int, j: dict) -> None:
        live = self.live.get(j["id"])
        done, total, speed = j["size_done"], j["size_total"], 0.0
        if live and j["status"] in ("downloading", "uploading"):
            done, total, speed = (live[0], live[1] or total, live[2])
        pct = int(1000 * done / total) if total else (1000 if j["status"] == "completed" else 0)
        info = ""
        if j.get("awaiting_approval"):
            info = "👁 " + self.t("dl.awaiting")
        elif j["error_code"]:
            k = "error." + j["error_code"]
            info = self.t(k) if self.t(k) != k else j["error_code"]
        elif j["scheduled_at"] and j["status"] == "waiting" and j["scheduled_at"] > datetime.now(timezone.utc).replace(tzinfo=None):
            info = "🕒 " + j["scheduled_at"].strftime("%m-%d %H:%M")
        vals = {0: j["filename"] or (j["url"] or j["id"][:8]), 2: LRM + (human_size(total) or "—"), 4: LRM + fmt_speed(speed),
                5: LRM + (fmt_eta(total - done, speed) if total else "—"), 6: str(j["priority"]),
                7: self.t("source." + j["source"]), 8: info}
        status = j["status"]
        st_item = self.table.item(i, 1)
        st_item.setText(self.status_label("paused" if False else status))
        st_item.setForeground(Qt.GlobalColor.white if False else self._qcolor(STATUS_COLORS[status]))
        for c, v in vals.items():
            it = self.table.item(i, c)
            if it.text() != v:
                it.setText(v)
        self.table.item(i, 0).setData(Qt.UserRole, j["id"])
        pb = self.table.cellWidget(i, 3)
        pb.setValue(pct)
        pb.setFormat(f"{LRM}{pct / 10:.1f}%")

    @staticmethod
    def _qcolor(hexs: str):
        from PySide6.QtGui import QColor
        return QColor(hexs)
