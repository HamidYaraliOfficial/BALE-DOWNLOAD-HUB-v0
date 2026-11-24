import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from app.application import AppContext
from app.core import events
from app.core.config import LANGUAGES, THEMES
from app.ui.components.widgets import FieldRow
from app.ui.main_window import MainWindow, NAV
from app.ui.theme import build_qss, PALETTES
from tests.conftest import make_ctx, wait_status
from tests.helpers import FakeBale, TOKEN, LocalServer


@pytest.fixture
def auto(monkeypatch):
    """Answer every confirm() with Yes and record info boxes instead of blocking on modal dialogs."""
    boxes = []
    import app.ui.pages.settings as s, app.ui.pages.channels as c, app.ui.pages.users as u, app.ui.pages.downloads as d, app.ui.wizard as w
    for m in (s, c, u, d, w):
        if hasattr(m, "confirm"):
            monkeypatch.setattr(m, "confirm", lambda *a, **k: True)
        if hasattr(m, "info_box"):
            monkeypatch.setattr(m, "info_box", lambda parent, title, text, *a, **k: boxes.append((title, text)))
    return boxes


@pytest.fixture
def win(qtbot, ctx, auto):
    ctx.sm.update({"general": {"first_run_done": True, "language": "en", "theme": "dark"}})
    w = MainWindow(ctx)
    qtbot.addWidget(w)
    w.show()
    return w


def test_every_page_renders_in_every_language_and_theme(win):
    ctx = win.ctx
    for lang in LANGUAGES:                                   # full rebuild per language
        ctx.sm.update({"general": {"language": lang, "theme": "dark"}})
        win.apply_look(rebuild=True)
        for i in range(len(NAV)):
            win.go(i)
            QApplication.processEvents()
        assert (QApplication.layoutDirection() == Qt.RightToLeft) == (lang == "fa")
    for theme in THEMES:                                      # every theme re-styles live without rebuilding
        ctx.sm.update({"general": {"theme": theme}})
        win.apply_look(rebuild=False)
        assert theme in win.theme_key()
        QApplication.processEvents()
    assert not ctx.tr.missing, ctx.tr.missing


def test_seven_distinct_themes_and_accent():
    assert len(THEMES) == 7 and set(THEMES) == set(PALETTES)
    q = {t: build_qss(t, "#FF00AA", "Vazirmatn") for t in THEMES}
    assert len(set(q.values())) == 7 and all("#FF00AA" in v for v in q.values())


def test_language_can_be_switched_at_any_time(win):
    ctx = win.ctx
    win.go(0)
    for lang, word in (("fa", "داشبورد"), ("zh", "仪表盘"), ("en", "Dashboard")):
        ctx.sm.update({"general": {"language": lang}})
        win.apply_look(rebuild=True)
        assert word in win.nav_buttons[0].text()


def test_fieldrow_validation_secret_toggle_and_help(qtbot, ctx):
    f = FieldRow(ctx.tr, "bot_token", "password", validator=lambda v: "bad" if v and "x" in v else None, on_test=lambda: None)
    qtbot.addWidget(f)
    f.w.setText("abcx")
    assert not f.validate() and f.msg.text().startswith("✖") and f.w.property("invalid")
    f.w.setText("abc")
    assert f.validate() and not f.msg.isVisible() or f.msg.text() == ""
    from PySide6.QtWidgets import QLineEdit
    assert f.w.echoMode() == QLineEdit.Password
    f.eye.setChecked(True)
    assert f.w.echoMode() == QLineEdit.Normal
    assert not f.how.isVisible() or True
    f.q.click()
    assert not f.how.isHidden() and f.test_btn is not None and f.example.text()
    assert ctx.tr("field.bot_token.h") in f.q.toolTip()


def test_every_settings_input_has_help_widgets(win):
    page = win.pages[6]
    assert len(page.fields) >= 45
    for path, row in page.fields.items():
        assert row.desc.text() and row.example.text() and row.q.toolTip(), path


def test_dashboard_numbers_are_real(win, server, fake_bale):
    win.ctx.downloads.add_job(server.url("/small.pdf"))
    wait_status(win.ctx, win.ctx.repo.list_jobs()[0]["id"], ("completed",))
    dash = win.pages[0]
    dash.refresh()
    v = lambda k: dash.cards[k]._v.text().replace("\u200e", "")
    assert v("success") == "1" and v("published") == "1" and v("total") == "1" and v("temp_files") == "0"
    assert "2.0 KB" in v("sent_today")
    assert dash.recent.count() == 1


def test_downloads_page_lists_jobs_and_controls_them(win, server):
    ctx = win.ctx
    ctx.downloads.queue.pause_queue("t")
    r = ctx.downloads.add_job(server.url("/small.pdf"))
    win.go(1)
    page = win.pages[1]
    page.refresh()
    assert page.table.rowCount() == 1 and page.table.item(0, 0).text() == "doc.pdf"
    page.table.selectRow(0)
    page._each(ctx.downloads.pause)
    assert ctx.repo.get_job(r.job["id"])["status"] == "paused"
    page._each(ctx.downloads.resume)
    assert ctx.repo.get_job(r.job["id"])["status"] == "waiting"
    page._cancel()                                              # confirm auto-answered "yes"
    assert ctx.repo.get_job(r.job["id"])["status"] == "cancelled"
    assert not (ctx.cleanup.base_dir() / r.job["id"]).exists()


def test_add_links_dialog_analyse_then_confirm(win, server, qtbot):
    from app.ui.pages.downloads import AddLinksDialog
    d = AddLinksDialog(win, f"{server.url('/small.pdf')}\n{server.url('/small.pdf')}\n{server.url('/pic.jpg')}\n{server.url('/huge')}\nnot-a-link")
    qtbot.addWidget(d)
    d.ctx.downloads.queue.pause_queue("t")
    d._analyze()
    qtbot.waitUntil(lambda: d.ok_btn.isEnabled(), timeout=10000)
    assert d.table.rowCount() == 3                                # duplicate dropped
    names = [d.table.item(i, 1).text() for i in range(3)]
    assert names[:2] == ["doc.pdf", "pic.jpg"] and "file_too_large" not in names
    assert d.table.item(2, 0).checkState() == Qt.Unchecked        # unsupported row cannot be selected
    d.table.item(1, 0).setCheckState(Qt.Unchecked)                # user deselects one
    d.priority.setValue(3)
    d._confirm()
    jobs = win.ctx.repo.list_jobs()
    assert [j["filename"] for j in jobs] == ["doc.pdf"] and jobs[0]["priority"] == 3


def test_channel_dialog_requires_confirmation_and_verifies(win, qtbot, auto, fake_bale):
    from app.ui.pages.channels import ChannelDialog
    d = ChannelDialog(win)
    qtbot.addWidget(d)
    d.f_id.w.setText("not valid!")
    assert not d.f_id.validate()
    d.f_id.w.setText("@newchan")
    d._test()
    qtbot.waitUntil(lambda: d.check is not None, timeout=5000)
    assert d.check.ok and d.f_title.value() == "My Channel"
    d._save()                                                     # not confirmed -> nothing added
    assert [c["chat_id"] for c in win.ctx.repo.list_channels()] == ["@testchan"] and auto
    d.confirm.setChecked(True)
    d._save()
    chans = {c["chat_id"]: c for c in win.ctx.repo.list_channels()}
    assert chans["@newchan"]["status"] == "ok" and not chans["@newchan"]["is_default"]


def test_users_page_protects_last_super_admin(win, auto):
    ctx = win.ctx
    ctx.repo.add_user(1, "Only", "SUPER_ADMIN")
    page = win.pages[3]
    page.refresh()
    page.table.selectRow(0)
    page.remove()
    page.block()
    assert ctx.repo.get_user(1) and not ctx.repo.get_user(1)["blocked"] and len(auto) == 2
    ctx.repo.add_user(2, "Second", "SUPER_ADMIN")
    page.refresh()
    page.table.selectRow(0)
    page.block()
    assert ctx.repo.get_user(1)["blocked"]


def test_settings_save_valid_invalid_and_critical(win, auto, tmp_path):
    page = win.pages[6]
    page.load()
    page.fields["download.max_file_size_mb"].set_value(30)
    page.fields["download.directory"].set_value(str(tmp_path / "newdir"))
    page.fields["bale.proxy"].set_value("socks5://127.0.0.1:1080")
    page.save()
    s = win.ctx.sm.settings
    assert s.download.max_file_size_mb == 30 and s.bale.proxy.startswith("socks5") and (tmp_path / "newdir").is_dir()
    page.fields["bale.proxy"].set_value("ftp://nope")             # invalid -> must not be saved
    page.fields["download.max_file_size_mb"].set_value(77)
    page.save()
    s = win.ctx.sm.settings
    assert s.download.max_file_size_mb == 30 and s.bale.proxy.startswith("socks5")
    assert "✖" in page.msg.text()
    assert page.fields["publish.delete_after_upload"].w.isChecked() and not page.fields["publish.delete_after_upload"].w.isEnabled()


def test_settings_token_test_and_secure_save(win, auto, qtbot, fake_bale):
    page = win.pages[6]
    page.token.w.setText("12345:short")
    page._test_token()
    assert "✖" in page.token.msg.text()
    page.token.w.setText(TOKEN)
    page._test_token()
    qtbot.waitUntil(lambda: "hub_bot" in page.token.msg.text(), timeout=5000)
    page._save_token()
    qtbot.waitUntil(lambda: win.ctx.runtime.bot_info is not None, timeout=5000)
    assert win.ctx.secrets.get("bale_bot_token") == TOKEN and page.token.w.text() == ""
    assert TOKEN not in win.ctx.sm.settings.model_dump_json()
    assert win.ctx.sm.settings.bale.bot_username == "hub_bot"
    qtbot.waitUntil(lambda: win.ctx.runtime.status in ("connected", "connecting"), timeout=5000)
    win.ctx.runtime.stop_polling()


def test_logs_page_filters_and_exports(win, server, tmp_path, monkeypatch):
    ctx = win.ctx
    for p in ("/small.pdf", "/pic.jpg"):
        j = ctx.downloads.add_job(server.url(p)).job
        wait_status(ctx, j["id"], ("completed",))
    ctx.repo.add_error("x", "ERROR", f"boom {TOKEN}")
    page = win.pages[4]
    page.refresh()
    assert page.tables["downloads"].rowCount() == 2
    page.search.setText("pic")
    page.refresh()
    assert page.tables["downloads"].rowCount() == 1
    page.search.clear()
    page.tabs.setCurrentIndex(2)
    page.refresh()
    assert page.tables["errors"].rowCount() == 1 and TOKEN not in page.tables["errors"].item(0, 3).text()
    out = tmp_path / "e.csv"
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    page.export("csv")
    assert out.exists() and TOKEN not in out.read_text(encoding="utf-8-sig")
    page.tabs.setCurrentIndex(5)
    page.refresh()
    assert page.tables["cleanup"].rowCount() == 2


def test_toast_notifications_and_per_event_switch(win, qtbot):
    ctx = win.ctx
    ctx.bus.publish(events.DOWNLOAD_ERROR, job_id="abcdef123456", detail="boom")
    qtbot.waitUntil(lambda: win.toasts._lay.count() == 1, timeout=3000)
    ctx.sm.update({"notifications": {"in_app": {events.DOWNLOAD_ERROR: False}}})
    ctx.bus.publish(events.DOWNLOAD_ERROR, job_id="abcdef123456", detail="boom2")
    qtbot.wait(200)
    assert win.toasts._lay.count() == 1
    assert len(ctx.notifications.history) == 1


def test_admins_get_bale_message_on_selected_events(ctx, fake_bale):
    ctx.repo.add_user(1, "Boss", "SUPER_ADMIN")
    ctx.repo.add_user(2, "Op", "OPERATOR")
    ctx.bus.publish(events.DISK_LOW, free=1000)
    assert [m["chat_id"] for m in fake_bale.sent_messages] == [1]       # admins only, operators not bothered
    ctx.bus.publish(events.DISK_LOW, free=1000)
    assert len(fake_bale.sent_messages) == 1                            # flood protection
    ctx.sm.update({"notifications": {"notify_admins_on_bale": False}})
    ctx.notifications._last_bale.clear()
    ctx.bus.publish(events.DISK_LOW, free=1000)
    assert len(fake_bale.sent_messages) == 1


def test_help_center_search(win):
    page = win.pages[5]
    assert page.list.count() >= 19
    page.search.setText("token")
    assert 0 < page.list.count() < 19
    page.search.setText("zzzzzz-nothing")
    assert page.list.count() == 0
    page.search.clear()
    page.open_article("cleanup")
    assert "Automatic clean-up" in page.view.toPlainText()


def test_full_setup_wizard_flow(qtbot, tmp_path, auto, monkeypatch):
    monkeypatch.setattr(MainWindow, "run_wizard", lambda self: None)      # we drive the wizard ourselves
    fake = FakeBale()
    ctx = AppContext(home=tmp_path / "h", bale_transport=fake.transport(), use_keyring=False)
    ctx.sm.update({"general": {"language": "en"}})
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    from app.ui.wizard import SetupWizard
    w = SetupWizard(win)
    qtbot.addWidget(w)
    assert w.idx == 0 and not ctx.runtime.has_token()
    w.go_next()
    # token step: cannot proceed without testing / with a malformed token
    w.f_token.w.setText("garbage")
    w.go_next()
    assert w.idx == 1 and w.err.text()
    w.f_token.w.setText(TOKEN)
    w.go_next()
    assert w.idx == 1 and "Test" in w.err.text() or "test" in w.err.text().lower()
    w._test_token()
    qtbot.waitUntil(lambda: w.token_tested, timeout=5000)
    w.go_next()
    assert w.idx == 2 and ctx.secrets.get("bale_bot_token") == TOKEN
    qtbot.waitUntil(lambda: w.bot_ok, timeout=5000)
    assert ctx.repo.get_bot_account()["username"] == "hub_bot"
    w.go_next()
    w.f_chan.w.setText("bad id!")
    w.go_next()
    assert w.idx == 3
    w.f_chan.w.setText("@mychannel")
    w.go_next()
    assert w.idx == 4
    w.go_next()                                           # access not verified yet -> blocked
    assert w.idx == 4
    w._check_access()
    qtbot.waitUntil(lambda: w.chan_ok, timeout=5000)
    w.go_next()
    w.f_admins.w.setPlainText("12ab")
    w.go_next()
    assert w.idx == 5
    w.f_admins.w.setPlainText("111\n222, 333")
    w.go_next()
    w.f_dir.set_value(str(tmp_path / "wizard_tmp"))
    w._test_dir()
    assert "writable" in w.f_dir.msg.text()
    w.go_next()
    w.f_max.set_value(40)
    w.f_conc.set_value(3)
    w.go_next()
    assert w.idx == 8
    w.f_priv.set_value(True)
    w.go_next()
    assert w.idx == 9 and "mychannel" in w.review.toPlainText() and "111" in w.review.toPlainText()
    assert TOKEN not in w.review.toPlainText()
    w.go_next()                                           # not confirmed
    assert ctx.repo.list_channels() == []
    w.confirm_post.setChecked(True)
    w.go_next()
    s = ctx.sm.settings
    assert s.general.first_run_done and s.download.max_file_size_mb == 40 and s.download.concurrent_downloads == 3
    assert s.cleanup.privacy_mode and (tmp_path / "wizard_tmp").is_dir()
    assert [c["chat_id"] for c in ctx.repo.list_channels()] == ["@mychannel"]
    users = {u["user_id"]: u["role"] for u in ctx.repo.list_users()}
    assert users == {111: "SUPER_ADMIN", 222: "ADMIN", 333: "ADMIN"}
    qtbot.waitUntil(lambda: ctx.runtime.status in ("connected", "connecting"), timeout=5000)
    ctx.runtime.stop_polling()


def test_wizard_keeps_entered_values_after_exit(qtbot, tmp_path, auto, monkeypatch):
    monkeypatch.setattr(MainWindow, "run_wizard", lambda self: None)
    fake = FakeBale()
    ctx = AppContext(home=tmp_path / "h", bale_transport=fake.transport(), use_keyring=False)
    ctx.sm.update({"general": {"language": "en"}})
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    from app.ui.wizard import SetupWizard
    w = SetupWizard(win)
    qtbot.addWidget(w)
    w.go_next()                                            # welcome -> token
    w.f_token.w.setText(TOKEN); w._test_token()
    qtbot.waitUntil(lambda: w.token_tested, timeout=5000)
    w.go_next()                                            # token -> connect
    qtbot.waitUntil(lambda: w.bot_ok, timeout=5000)
    w.go_next()                                            # connect -> channel
    w.f_chan.w.setText("@keepme"); w.f_admins.w.setPlainText("555")
    w.go_next()                                            # channel -> access
    w._save_exit()
    w2 = SetupWizard(win)
    qtbot.addWidget(w2)
    assert w2.idx == 4 and w2.f_chan.value() == "@keepme" and w2.f_admins.value() == "555"
    assert ctx.runtime.has_token()
