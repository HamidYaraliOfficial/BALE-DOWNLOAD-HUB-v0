"""Renders real screenshots of the running UI (offscreen) for the PDF/README. Uses a fake Bale server."""
import os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from tests.helpers import FakeBale, LocalServer
from tests.conftest import make_ctx
from app.ui.main_window import MainWindow
from app.ui.wizard import SetupWizard
OUT = Path(ROOT) / "docs" / "img"
fake = FakeBale()
ctx = make_ctx(Path(tempfile.mkdtemp()), fake)
ctx.sm.update({"general": {"first_run_done": True, "language": "fa", "theme": "windows11", "accent": "#0067C0"}})
ctx.repo.update_channel(1, status="ok")
ctx.add_admin(111, "مدیر")
with LocalServer() as srv:
    ctx.downloads.start()
    for p in ("/small.pdf", "/pic.jpg", "/file.bin", "/small.pdf?second=1"):
        ctx.downloads.add_job(srv.url(p))
    time.sleep(3)
    win = MainWindow(ctx); win.resize(1280, 800); win.show(); app.processEvents()
    for i, name in ((0, "dashboard"), (1, "downloads"), (2, "channels"), (4, "logs"), (6, "settings")):
        win.go(i); app.processEvents(); time.sleep(0.2); app.processEvents()
        win.grab().save(str(OUT / f"{name}.png"))
    win.pages[6].tabs.setCurrentIndex(2); app.processEvents(); win.grab().save(str(OUT / "settings_publish.png"))
    ctx.sm.update({"general": {"theme": "midnight_blue"}}); win.apply_look(); win.go(0); app.processEvents(); win.grab().save(str(OUT / "dashboard_dark.png"))
    ctx.sm.update({"general": {"theme": "windows11"}}); win.apply_look(); app.processEvents()
    for idx, name in ((1, "wizard_token"), (4, "wizard_access"), (9, "wizard_review")):
        w = SetupWizard(win); w.resize(780, 640); w.idx = idx
        if idx == 9: w.chan_ok = True; w.f_chan.set_value("@my_channel"); w.f_admins.set_value("111")
        w._show(); w.show(); app.processEvents(); w.grab().save(str(OUT / f"{name}.png")); w.close()
    win._closing = True; ctx.shutdown()
print("ok", sorted(p.name for p in OUT.iterdir()))
