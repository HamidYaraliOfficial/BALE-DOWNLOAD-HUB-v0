"""Entry point: python -m app.main"""
from __future__ import annotations

import sys


def selftest() -> int:
    """Headless smoke test used to verify a packaged build: migrations, translations, fonts, help, UI import."""
    import json
    import os
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.application import AppContext
    from app.core.paths import resource_path
    from app.ui.main_window import MainWindow
    app = QApplication(sys.argv)
    ctx = AppContext(home=tempfile.mkdtemp(), use_keyring=False)
    assert ctx.db.current_revision() == "0001", "migration failed"
    for lang in ("fa", "en", "zh"):
        assert len(ctx.tr.keys(lang)) > 600, f"translations missing: {lang}"
    assert (resource_path("fonts") / "Vazirmatn-Regular.ttf").exists(), "font missing"
    assert json.loads((resource_path("help") / "fa.json").read_text(encoding="utf-8"))["articles"], "help missing"
    win = MainWindow(ctx)
    win.show()
    app.processEvents()
    win._closing = True
    ctx.shutdown()
    print("SELFTEST OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import APP_NAME
    from app.application import AppContext
    from app.core import paths
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    lock = QLockFile(str(paths.app_home() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_NAME, "BALE DOWNLOAD HUB is already running.")
        return 1
    ctx = AppContext()
    win = MainWindow(ctx)
    ctx.start()
    win.show()
    rc = app.exec()
    lock.unlock()
    return rc


if __name__ == "__main__":
    sys.exit(main())
