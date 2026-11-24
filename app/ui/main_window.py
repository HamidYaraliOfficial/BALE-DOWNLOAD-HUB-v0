from __future__ import annotations

import shutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from app import __version__
from app.core import events
from app.services.caption import human_size
from app.services.notification_service import UI_TOAST
from app.ui import theme
from app.ui.components.widgets import EventBridge, ToastHost, confirm
from app.ui.pages.channels import ChannelsPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.downloads import DownloadsPage
from app.ui.pages.help_center import HelpCenterPage
from app.ui.pages.logs import LogsPage
from app.ui.pages.base import fmt_speed
from app.ui.pages.settings import SettingsPage
from app.ui.pages.users import UsersPage
from app.ui.wizard import RESTART, SetupWizard

NAV = [("dashboard", "🏠", DashboardPage), ("downloads", "⬇", DownloadsPage), ("channels", "📢", ChannelsPage),
       ("users", "👥", UsersPage), ("logs", "📊", LogsPage), ("help", "❓", HelpCenterPage), ("settings", "⚙", SettingsPage)]


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setMinimumSize(1100, 720)
        self.resize(1320, 820)
        self._closing = False
        self.bridge = EventBridge(ctx.bus)
        self.bridge.event.connect(self._on_event)
        self.root = QWidget()
        self.root.setObjectName("root")
        self.setCentralWidget(self.root)
        self.pages: list = []
        self.nav_buttons: list[QPushButton] = []
        self.toasts = ToastHost(self.root)
        self._build()
        self.apply_look(rebuild=False)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._status_tick)
        self.timer.start(1000)
        self._status_tick()
        if not ctx.sm.settings.general.first_run_done:
            QTimer.singleShot(300, self.run_wizard)

    # ------------------------------------------------------------------ build
    def _build(self, keep: int = 0) -> None:
        t = self.ctx.tr
        old = self.root.layout()
        if old is not None:
            QWidget().setLayout(old)             # detach old layout (and its widgets) for deletion
        for w in self.root.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if w is not self.toasts:
                w.deleteLater()
        lay = QHBoxLayout(self.root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(4)
        logo = QLabel("◈  BALE DOWNLOAD HUB")
        logo.setObjectName("h2")
        logo.setWordWrap(True)
        sl.addWidget(logo)
        sl.addSpacing(14)
        self.stack = QStackedWidget()
        self.pages, self.nav_buttons = [], []
        grp = QButtonGroup(self)
        for i, (key, icon, cls) in enumerate(NAV):
            b = QPushButton(f"{icon}   {t('nav.' + key)}".replace('&', '&&'))
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            grp.addButton(b, i)
            b.clicked.connect(lambda _c=False, idx=i: self.go(idx))
            sl.addWidget(b)
            self.nav_buttons.append(b)
            page = cls(self)
            self.pages.append(page)
            self.stack.addWidget(page)
        sl.addStretch(1)
        wiz = QPushButton("🧭  " + t("nav.wizard"))
        wiz.setObjectName("nav")
        wiz.clicked.connect(self.run_wizard)
        bell = QPushButton("🔔  " + t("nav.notifications"))
        bell.setObjectName("nav")
        bell.clicked.connect(self.show_notifications)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("hint")
        sl.addWidget(bell)
        sl.addWidget(wiz)
        sl.addWidget(ver)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.nav_buttons[keep].setChecked(True)
        self.stack.setCurrentIndex(keep)
        # status bar
        sb = self.statusBar()
        sb.clearMessage()
        for w in getattr(self, "_sb_widgets", []):
            sb.removeWidget(w)
            w.deleteLater()
        self.sb_bot, self.sb_queue, self.sb_disk, self.sb_speed = QLabel(), QLabel(), QLabel(), QLabel()
        self._sb_widgets = [self.sb_bot, self.sb_queue, self.sb_disk, self.sb_speed]
        for w in self._sb_widgets:
            sb.addPermanentWidget(w)
        self.toasts.raise_()

    def go(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.nav_buttons[idx].setChecked(True)
        self.pages[idx].refresh()

    def page(self, cls):
        return next(p for p in self.pages if isinstance(p, cls))

    def theme_key(self) -> tuple[str, str]:
        g = self.ctx.sm.settings.general
        return g.theme, g.accent

    # ------------------------------------------------------------------ look & feel
    def apply_look(self, rebuild: bool = False) -> None:
        g = self.ctx.sm.settings.general
        self.ctx.tr.set_language(g.language)
        theme.apply_theme(QApplication.instance(), g.theme, g.accent, g.language, self.ctx.tr.is_rtl)
        self.setWindowTitle("BALE DOWNLOAD HUB")
        if rebuild:
            cur = self.stack.currentIndex() if hasattr(self, "stack") else 0
            self._build(cur)
        for p in self.pages:
            p.refresh()
        self.toasts.reposition()

    # ------------------------------------------------------------------ events / toasts
    def toast(self, title: str, body: str, error: bool = False) -> None:
        self.toasts.show_toast(title, body, error)

    def _on_event(self, name: str, p: dict) -> None:
        if name == UI_TOAST:
            self.toast(p["title"], p["body"], p["error"])
            return
        for page in self.pages:
            page.on_event(name, p)

    def show_notifications(self) -> None:
        d = QDialog(self)
        d.setWindowTitle(self.ctx.tr("nav.notifications"))
        d.resize(520, 420)
        l = QVBoxLayout(d)
        lst = QListWidget()
        from datetime import datetime
        for n in reversed(self.ctx.notifications.history):
            lst.addItem(f"{datetime.fromtimestamp(n['ts']):%H:%M:%S}  {'⚠' if n['error'] else '•'}  {n['title']} — {n['body']}")
        if not lst.count():
            lst.addItem(self.ctx.tr("notif.empty"))
        l.addWidget(lst)
        d.exec()

    # ------------------------------------------------------------------ status bar
    def _status_tick(self) -> None:
        t, ctx = self.ctx.tr, self.ctx
        st = ctx.runtime.status
        dot = {"connected": "🟢", "connecting": "🟡", "error": "🔴", "stopped": "⚪"}.get(st, "⚪")
        self.sb_bot.setText(f"{dot} {t('bot.state.' + st)}")
        stats = ctx.repo.count_by_status()
        self.sb_queue.setText(f"⏳ {t('sb.queue')}: {stats.get('waiting', 0) + stats.get('paused', 0)}   ⚙ {ctx.downloads.queue.active_count()}")
        try:
            free = shutil.disk_usage(ctx.cleanup.base_dir()).free
        except OSError:
            free = 0
        self.sb_disk.setText(f"💾 {human_size(free)}")
        d, u = ctx.downloads.speeds.current()
        self.sb_speed.setText(f"⬇ {fmt_speed(d)}   ⬆ {fmt_speed(u)}")

    # ------------------------------------------------------------------ wizard / close
    def run_wizard(self) -> None:
        while True:
            w = SetupWizard(self)
            res = w.exec()
            if res != RESTART:
                break
        for p in self.pages:
            p.refresh()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.toasts.reposition()

    def closeEvent(self, ev: QCloseEvent) -> None:
        active = self.ctx.downloads.queue.active_count()
        if active and not self._closing:
            if not confirm(self, self.ctx.tr("common.confirm"), self.ctx.tr("app.confirm_exit", n=active),
                           self.ctx.tr("common.yes"), self.ctx.tr("common.no")):
                ev.ignore()
                return
        self._closing = True
        self.ctx.shutdown()
        ev.accept()
