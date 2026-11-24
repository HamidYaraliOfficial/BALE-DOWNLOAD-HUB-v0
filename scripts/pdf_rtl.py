"""Minimal RTL (Persian) layout toolkit for ReportLab: shaping (arabic-reshaper) + bidi per wrapped line."""
from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from bidi import get_display
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Image, Paragraph, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).resolve().parents[1] / "app" / "resources" / "fonts"
pdfmetrics.registerFont(TTFont("Vazir", str(FONT_DIR / "Vazirmatn-Regular.ttf")))
pdfmetrics.registerFont(TTFont("Vazir-Bold", str(FONT_DIR / "Vazirmatn-Bold.ttf")))
_reshaper = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False, "support_ligatures": True})

INK = colors.HexColor("#1B2230")
MUTED = colors.HexColor("#5B6475")
ACCENT = colors.HexColor("#0067C0")
LIGHT = colors.HexColor("#EEF3FA")


_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "«": "»", "»": "«", "<": ">", ">": "<"}


def _mirror_brackets(vis: str) -> str:
    """python-bidi reorders but does not mirror brackets; do it, except inside pure-Latin runs like f(x)."""
    out = []
    for i, ch in enumerate(vis):
        if ch in _MIRROR:
            prev = vis[i - 1] if i else " "
            nxt = vis[i + 1] if i + 1 < len(vis) else " "
            if prev.isascii() and prev.isalnum() and nxt.isascii() and nxt.isalnum():
                out.append(ch)
                continue
            out.append(_MIRROR[ch])
        else:
            out.append(ch)
    return "".join(out)


def shape(text: str) -> str:
    return _mirror_brackets(get_display(_reshaper.reshape(text), base_dir="R"))


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and pdfmetrics.stringWidth(shape(cand), font, size) > width:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


class RP(Flowable):
    """Right-to-left paragraph with correct shaping/bidi and page splitting."""

    def __init__(self, text="", size=10.5, leading=None, font="Vazir", color=INK, align="R", space_after=6,
                 indent=0, lines=None):
        super().__init__()
        self.text, self.size, self.font, self.color, self.align = text, size, font, color, align
        self.leading = leading or size * 1.75
        self.space_after, self.indent = space_after, indent
        self._lines = lines
        self.width = 0

    def wrap(self, aw, ah):
        self.width = aw
        if self._lines is None:
            self._lines = _wrap(self.text, self.font, self.size, aw - self.indent)
        self.height = len(self._lines) * self.leading + self.space_after
        return aw, self.height

    def split(self, aw, ah):
        self.wrap(aw, ah)
        fit = int((ah - self.space_after) // self.leading)
        if fit >= len(self._lines) or fit < 2:
            return [] if fit < 1 else [self] if fit >= len(self._lines) else []
        a = RP(self.text, self.size, self.leading, self.font, self.color, self.align, 0, self.indent, self._lines[:fit])
        b = RP(self.text, self.size, self.leading, self.font, self.color, self.align, self.space_after, self.indent, self._lines[fit:])
        return [a, b]

    def draw(self):
        c = self.canv
        c.setFont(self.font, self.size)
        c.setFillColor(self.color)
        y = self.height - self.space_after - self.size * 1.15
        for ln in self._lines:
            s = shape(ln)
            if self.align == "R":
                c.drawRightString(self.width - self.indent, y, s)
            elif self.align == "C":
                c.drawCentredString(self.width / 2, y, s)
            else:
                c.drawString(self.indent, y, s)
            y -= self.leading


class Code(Flowable):
    """LTR monospaced block (commands, paths)."""

    def __init__(self, text: str, size=9):
        super().__init__()
        self.lines, self.size = text.strip("\n").split("\n"), size

    def wrap(self, aw, ah):
        self.width = aw
        self.height = len(self.lines) * (self.size * 1.5) + 14
        return aw, self.height + 6

    def draw(self):
        c = self.canv
        c.setFillColor(colors.HexColor("#F3F4F6"))
        c.setStrokeColor(colors.HexColor("#D1D5DB"))
        c.roundRect(0, 6, self.width, self.height, 5, fill=1, stroke=1)
        c.setFillColor(colors.HexColor("#111827"))
        c.setFont("Courier", self.size)
        y = self.height - 4 - self.size
        for ln in self.lines:
            c.drawString(10, y, ln)
            y -= self.size * 1.5


class H(RP):
    def __init__(self, text, level=1):
        size = {1: 17, 2: 13}[level]
        super().__init__(text, size=size, font="Vazir-Bold", color=ACCENT if level == 1 else INK, space_after=8 if level == 1 else 4)
        self.level, self.title = level, text
        self.keepWithNext = True


class Callout(Flowable):
    def __init__(self, text, kind="note"):
        super().__init__()
        self.kind = kind
        self.col = {"note": ACCENT, "warn": colors.HexColor("#B45309"), "ok": colors.HexColor("#15803D")}[kind]
        self.p = RP(text, size=10, color=INK, space_after=0)

    def wrap(self, aw, ah):
        self.width = aw
        _w, h = self.p.wrap(aw - 28, ah)
        self.height = h + 14
        return aw, self.height + 6

    def draw(self):
        c = self.canv
        c.setFillColor({"note": LIGHT, "warn": colors.HexColor("#FEF3C7"), "ok": colors.HexColor("#DCFCE7")}[self.kind])
        c.roundRect(0, 6, self.width, self.height, 6, fill=1, stroke=0)
        c.setFillColor(self.col)
        c.rect(self.width - 5, 6, 5, self.height, fill=1, stroke=0)
        c.saveState()
        c.translate(8, 13)
        self.p.canv = c
        self.p.draw()
        c.restoreState()


def steps(items: list[str], width: float) -> Table:
    rows = []
    for i, t in enumerate(items, 1):
        rows.append([RP(t, space_after=2), RP(str(i), font="Vazir-Bold", color=colors.white, align="C", space_after=0, size=10)])
    t = Table(rows, colWidths=[width - 26, 22])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (1, 0), (1, -1), ACCENT),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("LINEBELOW", (0, 0), (-1, -2), 2, colors.white), ("TOPPADDING", (1, 0), (1, -1), 5)]))
    return t


def bullets(items: list[str]) -> list[Flowable]:
    return [RP("• " + t, space_after=3, indent=6) for t in items]


def table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    """Columns are given in logical (first = right-most) order."""
    def cell(t, bold=False, hdr=False):
        return RP(t, size=9, leading=15, font="Vazir-Bold" if bold else "Vazir", color=colors.white if hdr else INK, space_after=2)
    data = [[cell(h, True, True) for h in reversed(headers)]] + [[cell(c) for c in reversed(r)] for r in rows]
    t = Table(data, colWidths=list(reversed(widths)), repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
    return t


def picture(path: Path, width: float, caption: str | None = None) -> list[Flowable]:
    from PIL import Image as PI
    w, h = PI.open(path).size
    img = Image(str(path), width=width, height=width * h / w)
    out: list[Flowable] = [img]
    if caption:
        out.append(RP(caption, size=9, color=MUTED, align="C", space_after=10))
    return out
