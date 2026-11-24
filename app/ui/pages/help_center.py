from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from app.core.paths import resource_path
from app.ui.pages.base import Page


def load_help(lang: str) -> dict:
    for l in (lang, "en"):
        p = resource_path("help", f"{l}.json")
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"articles": [], "faq": []}


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).lower()


class HelpCenterPage(Page):
    title_key = "nav.help"

    def __init__(self, win):
        super().__init__(win)
        self.header(self.t("help.title"), self.t("help.sub"))
        self.data = load_help(self.ctx.sm.settings.general.language)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.t("help.search"))
        self.search.textChanged.connect(self._filter)
        self.root.addWidget(self.search)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        # articles
        w = QWidget()
        hl = QHBoxLayout(w)
        self.list = QListWidget()
        self.list.setMaximumWidth(280)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        hl.addWidget(self.list)
        hl.addWidget(self.view, 1)
        self.tabs.addTab(w, self.t("help.articles"))
        self.list.currentRowChanged.connect(self._show)
        # faq
        self.faq = QTextBrowser()
        self.faq.setOpenExternalLinks(True)
        self.tabs.addTab(self.faq, self.t("help.faq"))
        self._filter()

    def _filter(self) -> None:
        q = self.search.text().strip().lower()
        self.list.clear()
        for a in self.data["articles"]:
            if not q or q in a["title"].lower() or q in _plain(a["body"]):
                it = QListWidgetItem(a["title"])
                it.setData(Qt.UserRole, a["id"])
                self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.view.setHtml(f"<p>{self.t('help.none')}</p>")
        parts = [f"<h3>{f['q']}</h3><p>{f['a']}</p>" for f in self.data["faq"] if not q or q in f["q"].lower() or q in f["a"].lower()]
        self.faq.setHtml("".join(parts) or f"<p>{self.t('help.none')}</p>")

    def _show(self, row: int) -> None:
        it = self.list.item(row)
        if not it:
            return
        a = next(x for x in self.data["articles"] if x["id"] == it.data(Qt.UserRole))
        self.view.setHtml(f"<h2>{a['title']}</h2>{a['body']}")

    def open_article(self, aid: str) -> None:
        self.search.clear()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == aid:
                self.list.setCurrentRow(i)
        self.tabs.setCurrentIndex(0)
