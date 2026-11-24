"""Composition root: builds and wires every service. The UI and the tests both use AppContext."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from app.cleanup.manager import CleanupManager
from app.cleanup.scheduler import CleanupScheduler
from app.core import events, paths
from app.core.config import SettingsManager
from app.core.logger import DbErrorHandler, register_secret, set_level, setup_logging
from app.database.manager import DatabaseManager
from app.database.repository import Repository
from app.downloader.engine import DownloadEngine
from app.localization import Translator
from app.media.processor import MediaProcessor
from app.security.access_control import AccessController, Role
from app.security.secret_store import SecretStore
from app.security.url_safety import Resolver
from app.services.backup_service import BackupService
from app.services.bot_runtime import BotRuntime
from app.services.bot_service import BotService
from app.services.caption import DEFAULT_TEMPLATES
from app.services.download_service import DownloadService
from app.services.local_api import LocalApi
from app.services.notification_service import NotificationService
from app.services.publishing_service import PublishingService

log = logging.getLogger(__name__)


class AppContext:
    def __init__(self, home: Path | None = None, bale_transport: httpx.BaseTransport | None = None,
                 download_transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None,
                 allow_private: bool = False, use_keyring: bool = True):
        if home is not None:
            os.environ["BDH_HOME"] = str(home)
        self.home = paths.app_home()
        self.bus = events.EventBus()
        self.db = DatabaseManager(paths.db_path())
        self.db.migrate()
        self.repo = Repository(self.db)
        self.sm = SettingsManager(self.repo, self.bus)
        s = self.sm.settings
        setup_logging(paths.log_dir(), s.logging.level, s.logging.retention_days)
        set_level(s.logging.level)
        self._attach_db_log_handler()
        self.tr = Translator(s.general.language)
        self.secrets = SecretStore(self.home, use_keyring=use_keyring)
        self.secrets.get("bale_bot_token")                         # registers an existing token for log masking
        self.access = AccessController(self.repo)
        self.runtime = BotRuntime(self.repo, self.sm, self.secrets, self.bus, transport=bale_transport)
        self.cleanup = CleanupManager(self.repo, lambda: self.sm.settings, self.bus)
        self.engine = DownloadEngine(lambda: self.sm.settings.download, resolver, download_transport, allow_private)
        self.processor = MediaProcessor(lambda: self.sm.settings.download, lambda: self.sm.settings.media)
        self.publishing = PublishingService(self.repo, self.sm, self.runtime, self.bus)
        self.downloads = DownloadService(self.repo, self.sm, self.engine, self.processor, self.publishing,
                                         self.cleanup, self.bus, self.access)
        self.notifications = NotificationService(self.repo, self.sm, self.runtime, self.bus, self.tr)
        self.bot = BotService(self.repo, self.sm, self.runtime, self.downloads, self.access, self.tr, self.cleanup)
        self.scheduler = CleanupScheduler(self.cleanup, self.repo, lambda: self.sm.settings, self.bus,
                                          lambda: self.downloads.queue)
        self.backup = BackupService(self.db, self.repo, self.sm, on_restored=self._after_restore)
        self.local_api = LocalApi(self.repo, self.sm, self.downloads, self.secrets)
        self._seed_templates()
        self.bus.subscribe(events.SETTINGS_CHANGED, self._on_settings)
        self._started = False

    # ------------------------------------------------------------------
    def _attach_db_log_handler(self) -> None:
        root = logging.getLogger()
        if not any(isinstance(h, DbErrorHandler) for h in root.handlers):
            root.addHandler(DbErrorHandler(lambda comp, lvl, msg: self.repo.add_error(comp, lvl, msg)))

    def _seed_templates(self) -> None:
        if not self.repo.list_templates():
            for kind, (name, tpl) in DEFAULT_TEMPLATES.items():
                self.repo.save_template(kind, name, tpl, True)

    def _on_settings(self, _evt, settings=None, **_kw) -> None:
        s = settings or self.sm.settings
        self.tr.set_language(s.general.language)
        set_level(s.logging.level)
        try:
            self.local_api.apply_settings()
        except OSError as e:
            log.warning("local API could not start: %s", e)

    def _after_restore(self) -> None:
        self.downloads.queue.recover(self.sm.settings.download.auto_resume)
        self.tr.set_language(self.sm.settings.general.language)

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.downloads.start()
        self.scheduler.start()
        self.start_bot()
        try:
            self.local_api.apply_settings()
        except OSError as e:
            log.warning("local API could not start: %s", e)

    def start_bot(self) -> None:
        if self.sm.settings.bale.bot_enabled and self.runtime.has_token():
            self.runtime.start_polling(self.bot.handle)

    def add_admin(self, user_id: int, name: str = "", role: Role | None = None) -> None:
        if role is None:
            has_super = any(u["role"] == "SUPER_ADMIN" for u in self.repo.list_users())
            role = Role.ADMIN if has_super else Role.SUPER_ADMIN
        self.repo.add_user(user_id, name, role.name)
        self.repo.add_activity("user_added", f"{user_id} as {role.name}", 0, "user")

    def shutdown(self) -> None:
        self.local_api.stop()
        self.runtime.shutdown()
        self.scheduler.stop()
        self.downloads.shutdown()
        self.db.close()
