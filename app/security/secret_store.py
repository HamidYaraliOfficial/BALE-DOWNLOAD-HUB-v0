"""Token storage. Primary: OS credential vault via `keyring` (Windows Credential Manager).
Fallback (no usable keyring backend): Fernet-encrypted file in the app data dir.

Honest limit: the fallback key is derived from machine/user identifiers, so it stops
casual reading of the file (and accidental leaks through backups/exports), but it
cannot stop malware running as the same user. Prefer the OS vault.
"""
from __future__ import annotations

import base64
import getpass
import json
import logging
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.logger import register_secret

log = logging.getLogger(__name__)
SERVICE = "BaleDownloadHub"


def _machine_id() -> str:
    try:
        if os.name == "nt":
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(p):
                return Path(p).read_text().strip()
    except Exception:
        pass
    return str(uuid.getnode())


class SecretStore:
    def __init__(self, fallback_dir: Path, service: str = SERVICE, use_keyring: bool = True, backend=None):
        self._service = service
        self._dir = Path(fallback_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "secrets.enc"
        self._kr = None
        if backend is not None:
            self._kr = backend
        elif use_keyring:
            try:
                import keyring
                from keyring.backends import fail
                kr = keyring.get_keyring()
                if not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 1) > 0:
                    self._kr = keyring
            except Exception as e:  # pragma: no cover - environment dependent
                log.info("keyring unavailable, using encrypted file: %s", e)
        self.backend_name = "keyring" if self._kr is not None else "encrypted-file"

    # --- fallback file helpers
    def _fernet(self) -> Fernet:
        salt_file = self._dir / "secrets.salt"
        if not salt_file.exists():
            salt_file.write_bytes(os.urandom(16))
            self._chmod(salt_file)
        salt = salt_file.read_bytes()
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
        ident = f"{_machine_id()}|{getpass.getuser() if _has_user() else 'user'}".encode()
        return Fernet(base64.urlsafe_b64encode(kdf.derive(ident)))

    @staticmethod
    def _chmod(p: Path) -> None:
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def _read_file(self) -> dict[str, str]:
        if not self._file.exists():
            return {}
        try:
            return json.loads(self._fernet().decrypt(self._file.read_bytes()).decode())
        except (InvalidToken, ValueError):
            log.warning("secret file unreadable (different machine/user?)")
            return {}

    def _write_file(self, data: dict[str, str]) -> None:
        self._file.write_bytes(self._fernet().encrypt(json.dumps(data).encode()))
        self._chmod(self._file)

    # --- public API
    def set(self, name: str, value: str) -> None:
        register_secret(value)
        if self._kr is not None:
            self._kr.set_password(self._service, name, value)
            return
        d = self._read_file()
        d[name] = value
        self._write_file(d)

    def get(self, name: str) -> str | None:
        if self._kr is not None:
            v = self._kr.get_password(self._service, name)
        else:
            v = self._read_file().get(name)
        if v:
            register_secret(v)
        return v

    def delete(self, name: str) -> None:
        if self._kr is not None:
            try:
                self._kr.delete_password(self._service, name)
            except Exception:
                pass
            return
        d = self._read_file()
        if name in d:
            del d[name]
            self._write_file(d)


def _has_user() -> bool:
    try:
        getpass.getuser()
        return True
    except Exception:
        return False
