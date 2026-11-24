"""Small dependency-free chart widgets (QPainter) fed with REAL data from the repository."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.ui.theme import palette

PALETTE = ["#3B82F6", "#22C55E", "#F59E0B", "#A78BFA", "#EF4444", "#22D3EE", "#F472B6", "#94A3B8"]


class _Base(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.theme = ("dark", None)
        self.empty_text = "—"

    def set_theme(self, theme: str, accent: str) -> None:
        self.theme = (theme, accent)
        self.update()

    def pal(self) -> dict:
        return palette(*self.theme)

    def _empty(self, p: QPainter) -> None:
        p.setPen(QColor(self.pal()["muted"]))
        p.drawText(self.rect(), Qt.AlignCenter, self.empty_text)


class LineChart(_Base):
    """Multi-series line chart. `series` = {name: [values]}; `labels` = x labels."""

    def __init__(self, parent=None, fmt=lambda v: f"{v:g}"):
        super().__init__(parent)
        self.labels: list[str] = []
        self.series: dict[str, list[float]] = {}
        self.fmt = fmt

    def set_data(self, labels: list[str], series: dict[str, list[float]]) -> None:
        self.labels, self.series = labels, series
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.pal()
        allv = [v for s in self.series.values() for v in s]
        if not self.labels or not allv or max(allv) == 0:
            return self._empty(p)
        left, right, top, bottom = 46, 12, 12, 30
        r = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        vmax = max(allv) * 1.15
        p.setPen(QPen(QColor(pal["border"]), 1))
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, self.fmt(vmax * i / 4))
            p.setPen(QPen(QColor(pal["border"]), 1))
        n = len(self.labels)
        step = max(1, n // 7)
        for i, lab in enumerate(self.labels):
            if i % step == 0:
                x = r.left() + (r.width() * i / max(1, n - 1))
                p.setPen(QColor(pal["muted"]))
                p.drawText(QRectF(x - 24, r.bottom() + 6, 48, 16), Qt.AlignCenter, lab)
        for idx, (name, vals) in enumerate(self.series.items()):
            col = QColor(PALETTE[idx % len(PALETTE)])
            path = QPainterPath()
            for i, v in enumerate(vals):
                pt = QPointF(r.left() + r.width() * i / max(1, n - 1), r.bottom() - r.height() * v / vmax)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 2.2))
            p.drawPath(path)
            p.setBrush(col)
            for i, v in enumerate(vals):
                p.drawEllipse(QPointF(r.left() + r.width() * i / max(1, n - 1), r.bottom() - r.height() * v / vmax), 2.8, 2.8)
        # legend
        x = r.left() + 6
        p.setPen(QColor(pal["text"]))
        for idx, name in enumerate(self.series):
            p.setBrush(QColor(PALETTE[idx % len(PALETTE)]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, top + 2, 10, 10), 3, 3)
            p.setPen(QColor(pal["text"]))
            w = p.fontMetrics().horizontalAdvance(name)
            p.drawText(QRectF(x + 14, top - 2, w + 6, 18), Qt.AlignVCenter, name)
            x += w + 34


class BarChart(_Base):
    def __init__(self, parent=None, fmt=lambda v: f"{v:g}"):
        super().__init__(parent)
        self.items: list[tuple[str, float]] = []
        self.fmt = fmt

    def set_data(self, items: list[tuple[str, float]]) -> None:
        self.items = items
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.pal()
        if not self.items or max(v for _k, v in self.items) == 0:
            return self._empty(p)
        f = QFont(self.font())
        f.setPointSize(8)
        p.setFont(f)
        n = len(self.items)
        vmax = max(v for _k, v in self.items) * 1.15
        area = QRectF(10, 14, self.width() - 20, self.height() - 40)
        bw = area.width() / n
        for i, (lab, v) in enumerate(self.items):
            h = area.height() * v / vmax
            rect = QRectF(area.left() + i * bw + bw * 0.2, area.bottom() - h, bw * 0.6, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(PALETTE[i % len(PALETTE)]))
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(rect.left() - 10, rect.top() - 16, rect.width() + 20, 14), Qt.AlignCenter, self.fmt(v))
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(area.left() + i * bw, area.bottom() + 6, bw, 16), Qt.AlignCenter, lab)


class DonutChart(_Base):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[str, float, str | None]] = []

    def set_data(self, items: list[tuple[str, float, str | None]]) -> None:
        self.items = [(k, v, c) for k, v, c in items if v > 0]
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.pal()
        total = sum(v for _k, v, _c in self.items)
        if total <= 0:
            return self._empty(p)
        side = min(self.height() - 16, self.width() * 0.5)
        rect = QRectF(10, (self.height() - side) / 2, side, side)
        start = 90 * 16
        for i, (_k, v, c) in enumerate(self.items):
            span = -int(360 * 16 * v / total)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c or PALETTE[i % len(PALETTE)]))
            p.drawPie(rect, start, span)
            start += span
        p.setBrush(QColor(pal["surface"]))
        inner = rect.adjusted(side * 0.27, side * 0.27, -side * 0.27, -side * 0.27)
        p.drawEllipse(inner)
        p.setPen(QColor(pal["text"]))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(13)
        p.setFont(f)
        p.drawText(inner, Qt.AlignCenter, f"{total:g}")
        f.setBold(False)
        f.setPointSize(9)
        p.setFont(f)
        y = max(10, (self.height() - 22 * len(self.items)) / 2)
        x = rect.right() + 18
        for i, (k, v, c) in enumerate(self.items):
            p.setBrush(QColor(c or PALETTE[i % len(PALETTE)]))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y + 4, 10, 10), 3, 3)
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(x + 16, y, self.width() - x - 20, 18), Qt.AlignVCenter, f"{k}  ({v:g})")
            y += 22
