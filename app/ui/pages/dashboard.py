from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QListWidget, QScrollArea, QVBoxLayout, QWidget, QFrame

from app.services.caption import human_size
from app.ui.components.charts import BarChart, DonutChart, LineChart
from app.ui.components.widgets import Card, shadow
from app.ui.pages.base import Page, fmt_speed
from app.ui.theme import STATUS_COLORS


def _panel(title: str, widget: QWidget) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    h = QLabel(title)
    h.setObjectName("h2")
    lay.addWidget(h)
    lay.addWidget(widget, 1)
    shadow(f, 18, 40)
    return f


class DashboardPage(Page):
    title_key = "nav.dashboard"

    def __init__(self, win):
        super().__init__(win)
        self.header(self.t("dash.title"), self.t("dash.sub"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(14)

        keys = ["bot", "channels", "total", "success", "errors", "published", "queued", "active", "recv_today",
                "sent_today", "disk_used", "temp_files", "disk_free", "freed", "speed", "last_op"]
        self.cards: dict[str, Card] = {k: Card(self.t(f"dash.card.{k}")) for k in keys}
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, k in enumerate(keys):
            grid.addWidget(self.cards[k], i // 4, i % 4)
        lay.addLayout(grid)

        self.ch_daily = LineChart()
        self.ch_ratio = DonutChart()
        self.ch_types = DonutChart()
        self.ch_bw = LineChart(fmt=lambda v: human_size(v) or "0")
        self.ch_sizes = BarChart()
        self.ch_pub = BarChart()
        self.charts = [self.ch_daily, self.ch_ratio, self.ch_types, self.ch_bw, self.ch_sizes, self.ch_pub]
        g2 = QGridLayout()
        g2.setSpacing(12)
        g2.addWidget(_panel(self.t("dash.chart.daily"), self.ch_daily), 0, 0, 1, 2)
        g2.addWidget(_panel(self.t("dash.chart.ratio"), self.ch_ratio), 0, 2)
        g2.addWidget(_panel(self.t("dash.chart.types"), self.ch_types), 1, 0)
        g2.addWidget(_panel(self.t("dash.chart.bandwidth"), self.ch_bw), 1, 1, 1, 2)
        g2.addWidget(_panel(self.t("dash.chart.sizes"), self.ch_sizes), 2, 0)
        g2.addWidget(_panel(self.t("dash.chart.published"), self.ch_pub), 2, 1)
        for c in (0, 1, 2):
            g2.setColumnStretch(c, 1)
        lay.addLayout(g2)

        self.recent = QListWidget()
        self.recent.setMinimumHeight(180)
        self.activity = QListWidget()
        self.activity.setMinimumHeight(180)
        g3 = QGridLayout()
        g3.setSpacing(12)
        g3.addWidget(_panel(self.t("dash.recent_ops"), self.recent), 0, 0)
        g3.addWidget(_panel(self.t("dash.admin_activity"), self.activity), 0, 1)
        lay.addLayout(g3)
        lay.addStretch(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(2500)
        self.refresh()

    def _tick(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        ctx, t = self.ctx, self.t
        for c in self.charts:
            c.set_theme(*self.win.theme_key())
            c.empty_text = t("dash.no_data")
        st = ctx.repo.stats()
        usage = ctx.cleanup.usage()
        bot_state = ctx.runtime.status
        names = {"connected": t("bot.state.connected"), "connecting": t("bot.state.connecting"),
                 "error": t("bot.state.error"), "stopped": t("bot.state.stopped")}
        col = {"connected": "#22C55E", "connecting": "#F59E0B", "error": "#EF4444", "stopped": "#94A3B8"}[bot_state] \
            if bot_state in names else "#94A3B8"
        uname = ctx.sm.settings.bale.bot_username
        self.cards["bot"].set(names.get(bot_state, bot_state), f"@{uname}" if uname else t("dash.no_token") if not ctx.runtime.has_token() else "", col)
        chans = ctx.repo.list_channels()
        okc = sum(1 for c in chans if c["status"] == "ok")
        self.cards["channels"].set(f"{okc}/{len(chans)}", t("dash.channels_ok"),
                                   "#22C55E" if chans and okc == len(chans) else "#F59E0B" if chans else None)
        self.cards["total"].set(str(st["total"]))
        self.cards["success"].set(str(st["completed"]), color="#22C55E")
        self.cards["errors"].set(str(st["failed"]), t("dash.errors_logged", n=st["errors_logged"]),
                                 "#EF4444" if st["failed"] else None)
        self.cards["published"].set(str(st["published"]))
        self.cards["queued"].set(str(st["queued"]), t("dash.queue_paused") if ctx.downloads.queue.paused else "")
        self.cards["active"].set(str(st["active"]))
        self.cards["recv_today"].set(human_size(st["bytes_received_today"]) or "0 B")
        self.cards["sent_today"].set(human_size(st["bytes_sent_today"]) or "0 B")
        self.cards["disk_used"].set(human_size(usage["temp_bytes"]) or "0 B", t("dash.temp_dir"))
        self.cards["temp_files"].set(str(usage["temp_files"]))
        free_pct = (usage["disk_free"] / usage["disk_total"] * 100) if usage["disk_total"] else 0
        self.cards["disk_free"].set(human_size(usage["disk_free"]), f"{free_pct:.0f}% / {human_size(usage['disk_total'])}",
                                    "#EF4444" if usage["disk_free"] < ctx.sm.settings.download.min_free_disk_mb * 1048576 else None)
        self.cards["freed"].set(human_size(ctx.repo.total_bytes_freed()) or "0 B", t("dash.freed_hint"))
        down, up = ctx.downloads.speeds.current()
        self.cards["speed"].set(f"⬇ {fmt_speed(down)}", f"⬆ {fmt_speed(up)}")
        recent = ctx.repo.list_jobs(limit=8)
        self.cards["last_op"].set(self.status_label(recent[0]["status"]) if recent else "—",
                                  (recent[0]["filename"] or recent[0]["id"][:8]) if recent else "")

        s = ctx.repo.daily_series(14)
        self.ch_daily.set_data(s["labels"], {t("dash.series.downloads"): s["downloads"], t("dash.series.published"): s["published"]})
        self.ch_ratio.set_data([(t("dash.ok"), sum(s["ok"]), "#22C55E"), (t("dash.fail"), sum(s["failed"]), "#EF4444")])
        self.ch_types.set_data([(t(f"type.{k}"), v, None) for k, v in ctx.repo.type_distribution().items()])
        self.ch_bw.set_data(s["labels"], {t("dash.series.received"): s["bytes_received"], t("dash.series.sent"): s["bytes_sent"]})
        self.ch_sizes.set_data(list(ctx.repo.size_distribution().items()))
        self.ch_pub.set_data(list(zip(s["labels"][-7:], s["published"][-7:])))

        self.recent.clear()
        for j in recent:
            self.recent.addItem(f"{self.status_label(j['status'])}   {(j['filename'] or j['id'][:8])[:48]}   {human_size(j['size_total'])}")
        self.activity.clear()
        for a in ctx.repo.list_activity(limit=60):
            if a["category"] in ("user", "security"):
                self.activity.addItem(f"{a['ts']:%m-%d %H:%M}  {a['action']}  {a['detail'][:50]}")
                if self.activity.count() >= 8:
                    break
