from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.constants import CATEGORIES
from app.services.caption import human_size


class Page(QWidget):
    title_key = ""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.ctx = win.ctx
        self.tr_ = win.ctx.tr
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(14)

    def t(self, key: str, **kw) -> str:
        return self.tr_(key, **kw)

    def header(self, title: str, sub: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        box = QVBoxLayout()
        h = QLabel(title)
        h.setObjectName("title")
        box.addWidget(h)
        if sub:
            s = QLabel(sub)
            s.setObjectName("muted")
            s.setWordWrap(True)
            box.addWidget(s)
        row.addLayout(box, 1)
        self.root.addLayout(row)
        return row

    def refresh(self) -> None:
        pass

    def on_event(self, name: str, payload: dict) -> None:
        pass

    def status_label(self, status: str) -> str:
        from app.ui.theme import STATUS_ICONS
        return f"{STATUS_ICONS.get(status, '')} {self.t('status.' + status)}"


def fmt_speed(bps: float) -> str:
    return f"{human_size(bps)}/s" if bps else "—"


def fmt_eta(remaining: float, speed: float) -> str:
    if not speed or remaining <= 0:
        return "—"
    s = int(remaining / speed)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
