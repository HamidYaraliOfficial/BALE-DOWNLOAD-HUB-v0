"""Reusable widgets: Card, FieldRow (every input with help), ToastHost, EventBridge, helpers."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPropertyAnimation, QSize, Qt, QTimer, Signal, QUrl, QEasingCurve
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from app.core.constants import CATEGORIES

HELP_URL = "https://docs.bale.ai/"


class EventBridge(QObject):
    """Thread-safe hop from the core EventBus (any thread) to Qt signals (GUI thread)."""
    event = Signal(str, dict)

    def __init__(self, bus):
        super().__init__()
        def _forward(evt, /, **payload):          # positional-only: payloads may contain a 'name' key
            self.event.emit(evt, payload)
        bus.subscribe("*", _forward)


def shadow(w: QWidget, blur: int = 24, alpha: int = 60) -> None:
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 3)
    eff.setColor(QColor(0, 0, 0, alpha))
    w.setGraphicsEffect(eff)


def confirm(parent, title: str, text: str, yes: str, no: str) -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    b_yes = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton(no, QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is b_yes


def info_box(parent, title: str, text: str, ok: str = "OK", error: bool = False) -> None:
    box = QMessageBox(QMessageBox.Critical if error else QMessageBox.Information, title, text, parent=parent)
    box.addButton(ok, QMessageBox.AcceptRole)
    box.exec()


class Card(QFrame):
    def __init__(self, title: str = "", value: str = "—", hint: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._t, self._v, self._h = QLabel(title), QLabel(value), QLabel(hint)
        self._t.setObjectName("muted")
        self._v.setObjectName("value")
        self._h.setObjectName("hint")
        self._h.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(2)
        for w in (self._t, self._v, self._h):
            lay.addWidget(w)
        shadow(self, 18, 40)
        self.setMinimumHeight(96)

    def set(self, value: str, hint: str | None = None, color: str | None = None) -> None:
        self._v.setText("\u200e" + value if value and value[0].isdigit() else value)
        self._v.setStyleSheet(f"color: {color};" if color else "")
        if hint is not None:
            self._h.setText(hint)

    def set_title(self, t: str) -> None:
        self._t.setText(t)


class ToastHost(QWidget):
    """Stack of auto-fading in-app notifications (bottom corner)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self._lay.setAlignment(Qt.AlignBottom)
        self.setFixedWidth(340)
        self.raise_()

    def reposition(self) -> None:
        p = self.parentWidget()
        h = min(p.height() - 60, 400)
        rtl = p.layoutDirection() == Qt.RightToLeft
        x = 16 if rtl else p.width() - self.width() - 16
        self.setGeometry(x, p.height() - h - 40, self.width(), h)
        self.raise_()

    def show_toast(self, title: str, body: str, error: bool = False, ms: int = 5000) -> QFrame:
        f = QFrame()
        f.setObjectName("toast")
        f.setStyleSheet(f"QFrame#toast {{ border-{'left' if self.layoutDirection() == Qt.LeftToRight else 'right'}: 4px solid "
                        f"{'#EF4444' if error else '#22C55E'}; }}")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(12, 8, 12, 8)
        t = QLabel(f"<b>{title}</b>")
        b = QLabel(body)
        b.setWordWrap(True)
        b.setObjectName("muted")
        lay.addWidget(t)
        lay.addWidget(b)
        eff = QGraphicsOpacityEffect(f)
        f.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", f)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        f._anim = anim
        self._lay.addWidget(f)
        while self._lay.count() > 4:
            old = self._lay.takeAt(0).widget()
            if old:
                old.deleteLater()
        self.reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(ms, lambda: self._fade(f, eff))
        return f

    def _fade(self, f: QFrame, eff) -> None:
        try:
            a = QPropertyAnimation(eff, b"opacity", f)
            a.setDuration(400)
            a.setStartValue(1.0)
            a.setEndValue(0.0)
            a.finished.connect(f.deleteLater)
            a.start()
            f._anim2 = a
        except RuntimeError:
            pass


class FieldRow(QFrame):
    """One setting/input with: title, purpose, how-to-get-it, example, show/hide (secrets), instant
    validation with a readable error, a Test button and an official help link."""
    changed = Signal()

    def __init__(self, tr, fid: str, kind: str = "text", *, options: list[tuple[str, str]] | None = None,
                 minimum: float = 0, maximum: float = 1_000_000, step: float = 1, suffix: str = "",
                 validator: Callable[[object], str | None] | None = None, on_test: Callable[[], None] | None = None,
                 help_url: str | None = HELP_URL, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.tr_, self.fid, self.kind, self._validator = tr, fid, kind, validator
        self.setObjectName("panel")
        self.setProperty("fid", fid)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(5)
        head = QHBoxLayout()
        self.title = QLabel(f"<b>{tr(f'field.{fid}.t')}</b>")
        self.q = QPushButton("?")
        self.q.setObjectName("icon")
        self.q.setFixedWidth(28)
        self.q.setCursor(Qt.PointingHandCursor)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.q)
        root.addLayout(head)
        self.desc = QLabel(tr(f"field.{fid}.d"))
        self.desc.setObjectName("muted")
        self.desc.setWordWrap(True)
        root.addWidget(self.desc)
        self.how = QLabel(tr(f"field.{fid}.h"))
        self.how.setWordWrap(True)
        self.how.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.how.setVisible(False)
        self.how.setStyleSheet("padding: 8px; border-radius: 8px; background: rgba(127,127,127,0.12);")
        root.addWidget(self.how)
        self.q.clicked.connect(lambda: self.how.setVisible(not self.how.isVisible()))
        self.q.setToolTip(f"{tr(f'field.{fid}.d')}\n\n{tr(f'field.{fid}.h')}\n\n{tr('common.example')}: \u202a{tr(f'field.{fid}.e')}\u202c")

        # --- input
        row = QHBoxLayout()
        self._multi: dict[str, QCheckBox] = {}
        if kind in ("text", "password"):
            self.w = QLineEdit()
            self.w.setPlaceholderText(placeholder or tr(f"field.{fid}.e"))
            if kind == "password":
                self.w.setEchoMode(QLineEdit.Password)
            self.w.textChanged.connect(self._on_change)
        elif kind == "multiline":
            self.w = QPlainTextEdit()
            self.w.setFixedHeight(90)
            self.w.setPlaceholderText(placeholder or tr(f"field.{fid}.e"))
            self.w.textChanged.connect(self._on_change)
        elif kind == "int":
            self.w = QSpinBox()
            self.w.setRange(int(minimum), int(maximum))
            self.w.setSingleStep(int(step))
            self.w.setSuffix(f" {suffix}" if suffix else "")
            self.w.setGroupSeparatorShown(True)
            self.w.valueChanged.connect(self._on_change)
        elif kind == "float":
            self.w = QDoubleSpinBox()
            self.w.setRange(minimum, maximum)
            self.w.setSingleStep(step)
            self.w.setSuffix(f" {suffix}" if suffix else "")
            self.w.valueChanged.connect(self._on_change)
        elif kind == "bool":
            self.w = QCheckBox(tr(f"field.{fid}.t"))
            self.w.stateChanged.connect(self._on_change)
            self.title.setVisible(False)
        elif kind == "combo":
            self.w = QComboBox()
            for val, label in options or []:
                self.w.addItem(label, val)
            self.w.currentIndexChanged.connect(self._on_change)
        elif kind == "path":
            self.w = QLineEdit()
            self.w.textChanged.connect(self._on_change)
        elif kind == "color":
            self.w = QPushButton()
            self._color = "#3B82F6"
            self.w.clicked.connect(self._pick_color)
        elif kind == "multicheck":
            self.w = QWidget()
            hl = QHBoxLayout(self.w)
            hl.setContentsMargins(0, 0, 0, 0)
            for val, label in options or [(c, tr(f"type.{c}")) for c in CATEGORIES]:
                cb = QCheckBox(label)
                cb.stateChanged.connect(self._on_change)
                self._multi[val] = cb
                hl.addWidget(cb)
            hl.addStretch(1)
        else:
            raise ValueError(kind)
        row.addWidget(self.w, 1)
        if kind == "password":
            self.eye = QPushButton("👁")
            self.eye.setObjectName("icon")
            self.eye.setToolTip(tr("common.show_hide"))
            self.eye.setCheckable(True)
            self.eye.toggled.connect(lambda on: self.w.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
            row.addWidget(self.eye)
        if kind == "path":
            b = QPushButton(tr("common.browse"))
            b.clicked.connect(self._browse)
            row.addWidget(b)
        self.test_btn = None
        if on_test:
            self.test_btn = QPushButton(tr("common.test"))
            self.test_btn.clicked.connect(on_test)
            row.addWidget(self.test_btn)
        if help_url:
            h = QPushButton("↗ " + tr("common.official_help"))
            h.setToolTip(help_url)
            h.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(help_url)))
            row.addWidget(h)
        root.addLayout(row)
        self.example = QLabel(f"{tr('common.example')}: \u202a{tr(f'field.{fid}.e')}\u202c")
        self.example.setObjectName("hint")
        self.example.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.example)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setVisible(False)
        root.addWidget(self.msg)
        self._loading = False

    # ------------------------------------------------------------ value access
    def value(self):
        k = self.kind
        if k in ("text", "password", "path"):
            return self.w.text().strip()
        if k == "multiline":
            return self.w.toPlainText().strip()
        if k in ("int", "float"):
            return self.w.value()
        if k == "bool":
            return self.w.isChecked()
        if k == "combo":
            return self.w.currentData()
        if k == "color":
            return self._color
        if k == "multicheck":
            return [v for v, cb in self._multi.items() if cb.isChecked()]

    def set_value(self, v) -> None:
        self._loading = True
        k = self.kind
        if k in ("text", "password", "path"):
            self.w.setText("" if v is None else str(v))
        elif k == "multiline":
            self.w.setPlainText("" if v is None else str(v))
        elif k in ("int", "float"):
            self.w.setValue(v)
        elif k == "bool":
            self.w.setChecked(bool(v))
        elif k == "combo":
            i = self.w.findData(v)
            self.w.setCurrentIndex(max(0, i))
        elif k == "color":
            self._color = v
            self._paint_color()
        elif k == "multicheck":
            for val, cb in self._multi.items():
                cb.setChecked(val in (v or []))
        self._loading = False
        self.validate()

    def lock(self, on: bool = True) -> None:
        self.w.setEnabled(not on)

    # ------------------------------------------------------------ validation / feedback
    def validate(self) -> bool:
        err = self._validator(self.value()) if self._validator else None
        self._show(err, ok=False)
        if isinstance(self.w, QLineEdit):
            self.w.setProperty("invalid", bool(err))
            self.w.style().unpolish(self.w)
            self.w.style().polish(self.w)
        return not err

    def set_error(self, text: str) -> None:
        self._show(text, ok=False)

    def set_test_result(self, ok: bool, text: str) -> None:
        self.msg.setStyleSheet(f"color: {'#22C55E' if ok else '#EF4444'};")
        self.msg.setText(("✔ " if ok else "✖ ") + text)
        self.msg.setVisible(True)

    def _show(self, text: str | None, ok: bool) -> None:
        if text:
            self.msg.setStyleSheet("color: #EF4444;")
            self.msg.setText("✖ " + text)
            self.msg.setVisible(True)
        elif self.msg.text().startswith("✖ ") and self._validator:
            self.msg.setVisible(False)
            self.msg.setText("")

    def _on_change(self, *_a) -> None:
        if self._loading:
            return
        self.validate()
        self.changed.emit()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, self.tr_("common.browse"), self.w.text() or "")
        if d:
            self.w.setText(d)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._paint_color()
            self.changed.emit()

    def _paint_color(self) -> None:
        self.w.setText(self._color.upper())
        self.w.setStyleSheet(f"background:{self._color}; color:{'#fff' if QColor(self._color).lightness() < 150 else '#111'}; font-weight:600;")


def clear_layout(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            clear_layout(it.layout())
