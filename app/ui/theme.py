"""Seven built-in themes + accent colour + per-language fonts, rendered to a Qt style sheet."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.core.paths import resource_path

PALETTES: dict[str, dict[str, str]] = {
    "dark":          dict(bg="#14161B", surface="#1C1F26", surface2="#252932", border="#2F3440", text="#E6E8EC", muted="#8A91A0", accent="#3B82F6"),
    "light":         dict(bg="#F4F6FA", surface="#FFFFFF", surface2="#EEF1F6", border="#DCE1EA", text="#1B2230", muted="#6B7385", accent="#2563EB"),
    "windows11":     dict(bg="#F3F3F3", surface="#FBFBFB", surface2="#EDEDED", border="#E0E0E0", text="#1A1A1A", muted="#605E5C", accent="#0067C0"),
    "midnight_blue": dict(bg="#0B1226", surface="#111B36", surface2="#18254A", border="#243460", text="#DDE6FF", muted="#8093C4", accent="#5B8DEF"),
    "graphite":      dict(bg="#202124", surface="#2B2D31", surface2="#35373C", border="#44474D", text="#EAEAEA", muted="#9AA0A6", accent="#9AA7B8"),
    "emerald":       dict(bg="#0E1A17", surface="#14241F", surface2="#1B3029", border="#254238", text="#DFF5EC", muted="#7FA595", accent="#10B981"),
    "crimson":       dict(bg="#1A0F12", surface="#251419", surface2="#311B21", border="#4A2630", text="#F7E4E8", muted="#B38791", accent="#E11D48"),
}
STATUS_COLORS = {
    "waiting": "#94A3B8", "validating": "#38BDF8", "downloading": "#3B82F6", "paused": "#F59E0B",
    "processing": "#A78BFA", "uploading": "#22D3EE", "completed": "#22C55E", "failed": "#EF4444",
    "cancelled": "#6B7280", "cleanup": "#F472B6",
}
STATUS_ICONS = {
    "waiting": "⏳", "validating": "🔍", "downloading": "⬇", "paused": "⏸", "processing": "⚙",
    "uploading": "⬆", "completed": "✔", "failed": "✖", "cancelled": "⊘", "cleanup": "🧹",
}
FONTS = {
    "fa": ["Vazirmatn", "Segoe UI", "Tahoma"],
    "en": ["Segoe UI", "Inter", "Arial"],
    "zh": ["Microsoft YaHei UI", "Noto Sans CJK SC", "PingFang SC", "Segoe UI"],
}
_fonts_loaded = False


def load_bundled_fonts() -> None:
    global _fonts_loaded
    if _fonts_loaded:
        return
    for f in resource_path("fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))
    _fonts_loaded = True


def palette(theme: str, accent: str | None = None) -> dict[str, str]:
    p = dict(PALETTES.get(theme, PALETTES["dark"]))
    if accent:
        p["accent"] = accent
    return p


def is_dark(theme: str) -> bool:
    return theme not in ("light", "windows11")


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() * (1 - t) + cb.red() * t), int(ca.green() * (1 - t) + cb.green() * t),
                  int(ca.blue() * (1 - t) + cb.blue() * t)).name()


def build_qss(theme: str, accent: str, font_family: str, rtl: bool = False) -> str:
    p = palette(theme, accent)
    acc = p["accent"]
    acc_h = _mix(acc, "#FFFFFF", 0.18)
    on_acc = "#FFFFFF" if QColor(acc).lightness() < 150 else "#111111"
    hover = _mix(p["surface2"], p["text"], 0.06)
    return f"""
* {{ font-family: "{font_family}"; font-size: 10pt; color: {p['text']}; outline: 0; }}
QMainWindow, QDialog, QWidget#root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['bg']}; }}
QWidget#sidebar {{ background: {p['surface']}; border: none; }}
QFrame#card, QFrame#panel {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QLabel#title {{ font-size: 18pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
QLabel#muted, QLabel#hint {{ color: {p['muted']}; }}
QLabel#value {{ font-size: 19pt; font-weight: 700; }}
QLabel#hint {{ font-size: 9pt; }}
QLabel {{ background: transparent; }}
QPushButton {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ background: {hover}; border-color: {acc}; }}
QPushButton:pressed {{ background: {p['border']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['surface']}; }}
QPushButton#primary {{ background: {acc}; color: {on_acc}; border: 1px solid {acc}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {acc_h}; }}
QPushButton#danger {{ background: transparent; color: #EF4444; border: 1px solid #EF4444; }}
QPushButton#danger:hover {{ background: #EF444422; }}
QPushButton#nav {{ background: transparent; border: none; border-radius: 10px; padding: 11px 14px; text-align: {'right' if rtl else 'left'}; }}
QPushButton#nav:hover {{ background: {p['surface2']}; }}
QPushButton#nav:checked {{ background: {acc}; color: {on_acc}; font-weight: 600; }}
QPushButton#icon {{ padding: 4px 8px; min-width: 22px; }}
QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {acc}; selection-color: {on_acc}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {acc}; }}
QLineEdit[invalid="true"] {{ border: 1px solid #EF4444; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']}; selection-background-color: {acc}; selection-color: {on_acc}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p['border']}; background: {p['surface2']}; }}
QCheckBox::indicator:checked {{ background: {acc}; border-color: {acc}; }}
QTableView, QTableWidget, QListWidget, QTreeWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
    gridline-color: {p['border']}; alternate-background-color: {p['surface2']}; selection-background-color: {acc}55; selection-color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface2']}; border: none; border-bottom: 1px solid {p['border']}; padding: 8px; font-weight: 600; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {acc}; color: {on_acc}; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; top: -1px; background: {p['bg']}; }}
QTabBar::tab {{ background: transparent; padding: 9px 16px; border-bottom: 2px solid transparent; color: {p['muted']}; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {acc}; font-weight: 600; }}
QProgressBar {{ background: {p['surface2']}; border: none; border-radius: 6px; text-align: center; height: 12px; max-height: 12px; font-size: 8pt; }}
QProgressBar::chunk {{ background: {acc}; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {p['surface2']}; color: {p['text']}; border: 1px solid {acc}; padding: 6px; border-radius: 6px; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {acc}; color: {on_acc}; }}
QStatusBar {{ background: {p['surface']}; border-top: 1px solid {p['border']}; }}
QStatusBar QLabel {{ padding: 0 8px; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 12px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['muted']}; }}
QFrame#toast {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px; }}
"""


def pick_font(lang: str) -> str:
    db = QFontDatabase.families()
    for fam in FONTS.get(lang, FONTS["en"]):
        if fam in db:
            return fam
    return QApplication.font().family()


def apply_theme(app: QApplication, theme: str, accent: str, lang: str, rtl: bool) -> None:
    from PySide6.QtCore import Qt
    load_bundled_fonts()
    fam = pick_font(lang)
    f = QFont(fam)
    f.setPointSize(10)
    app.setFont(f)
    app.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    app.setStyleSheet(build_qss(theme, accent, fam, rtl))
