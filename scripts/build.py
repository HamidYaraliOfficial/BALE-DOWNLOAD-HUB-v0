"""PyInstaller build. Usage: python scripts/build.py [onefile]
Produces dist/BALE_DOWNLOAD_HUB/BALE_DOWNLOAD_HUB.exe (onedir, default) or dist/BALE_DOWNLOAD_HUB.exe (onefile)."""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sep = os.pathsep


def main() -> int:
    import PyInstaller.__main__ as pi
    onefile = "onefile" in sys.argv
    for d in ("build", "dist"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    args = [
        str(ROOT / "app" / "main.py"), "--name", "BALE_DOWNLOAD_HUB", "--noconfirm", "--clean",
        "--onefile" if onefile else "--onedir", "--windowed", "--paths", str(ROOT),
        "--add-data", f"{ROOT / 'app' / 'resources'}{sep}app/resources",
        "--add-data", f"{ROOT / 'app' / 'localization'}{sep}app/localization",
        "--add-data", f"{ROOT / 'app' / 'database' / 'migrations'}{sep}app/database/migrations",
        "--collect-submodules", "yt_dlp", "--collect-submodules", "alembic", "--collect-data", "alembic",
        "--collect-submodules", "keyring.backends", "--hidden-import", "sqlalchemy.dialects.sqlite",
        "--hidden-import", "app.database.migrations.env",
        "--exclude-module", "tkinter", "--exclude-module", "pytest",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
    ]
    if sys.platform == "win32":
        ico = ROOT / "app" / "resources" / "app.ico"
        if ico.exists():
            args += ["--icon", str(ico)]
    pi.run(args)
    out = ROOT / "dist" / ("BALE_DOWNLOAD_HUB.exe" if onefile and sys.platform == "win32" else "BALE_DOWNLOAD_HUB")
    print("OUTPUT:", out)
    return 0 if out.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
