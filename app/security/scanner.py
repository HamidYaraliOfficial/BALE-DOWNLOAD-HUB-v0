"""Optional local antivirus scan. 'unavailable' is NEVER reported as clean."""
from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    status: str          # clean | infected | unavailable | error
    engine: str = ""
    detail: str = ""


def _defender_path() -> str | None:
    if os.name != "nt":
        return None
    cands = glob.glob(os.path.expandvars(r"%ProgramData%\Microsoft\Windows Defender\Platform\*\MpCmdRun.exe"))
    cands += [os.path.expandvars(r"%ProgramFiles%\Windows Defender\MpCmdRun.exe")]
    cands = [c for c in cands if os.path.exists(c)]
    return sorted(cands)[-1] if cands else None


def available_engines() -> list[str]:
    out = []
    if _defender_path():
        out.append("defender")
    if shutil.which("clamscan"):
        out.append("clamav")
    return out


def scan_file(path: str, timeout: int = 300) -> ScanResult:
    """Run the first locally installed engine. Arguments are passed as a list (no shell)."""
    try:
        d = _defender_path()
        if d:
            r = subprocess.run([d, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return ScanResult("clean", "defender")
            if r.returncode == 2:
                return ScanResult("infected", "defender", (r.stdout or "")[-300:])
            return ScanResult("error", "defender", f"exit code {r.returncode}")
        c = shutil.which("clamscan")
        if c:
            r = subprocess.run([c, "--no-summary", path], capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0:
                return ScanResult("clean", "clamav")
            if r.returncode == 1:
                return ScanResult("infected", "clamav", (r.stdout or "")[-300:])
            return ScanResult("error", "clamav", f"exit code {r.returncode}")
    except subprocess.TimeoutExpired:
        return ScanResult("error", "", "scan timed out")
    except OSError as e:
        return ScanResult("error", "", str(e))
    return ScanResult("unavailable", "", "no local antivirus engine found")
