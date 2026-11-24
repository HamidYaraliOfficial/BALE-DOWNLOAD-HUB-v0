"""Validated application settings persisted in the `settings` table (no secrets inside)."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core import events
from app.core.constants import CATEGORIES
from app.core.exceptions import ConfigError

SETTINGS_KEY = "app_settings"
THEMES = ["dark", "light", "windows11", "midnight_blue", "graphite", "emerald", "crimson"]
LANGUAGES = ["fa", "en", "zh"]
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class GeneralSettings(_Base):
    language: str = "fa"
    theme: str = "dark"
    accent: str = "#3B82F6"
    first_run_done: bool = False
    check_updates: bool = False        # off by default: no network call without consent
    update_feed_url: str = ""
    show_tooltips: bool = True

    @field_validator("language")
    @classmethod
    def _lang(cls, v):
        if v not in LANGUAGES:
            raise ValueError("unsupported language")
        return v

    @field_validator("theme")
    @classmethod
    def _theme(cls, v):
        if v not in THEMES:
            raise ValueError("unknown theme")
        return v

    @field_validator("accent")
    @classmethod
    def _accent(cls, v):
        import re
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("accent must be #RRGGBB")
        return v


class BaleSettings(_Base):
    api_base: str = "https://tapi.bale.ai"
    bot_username: str = ""
    bot_enabled: bool = True
    polling_interval_s: float = Field(2.0, ge=0.5, le=60)
    connect_timeout_s: float = Field(10.0, ge=1, le=120)
    read_timeout_s: float = Field(30.0, ge=1, le=600)
    upload_timeout_s: float = Field(900.0, ge=10, le=7200)
    retry_count: int = Field(3, ge=0, le=10)
    retry_backoff_s: float = Field(2.0, ge=0.1, le=120)
    proxy: str = ""
    require_confirmation: bool = False

    @field_validator("api_base")
    @classmethod
    def _base(cls, v):
        v = v.strip().rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("API base must start with https://")
        return v

    @field_validator("bot_username")
    @classmethod
    def _uname(cls, v):
        v = v.strip().lstrip("@")
        import re
        if v and not re.fullmatch(r"[A-Za-z0-9_]{3,64}", v):
            raise ValueError("invalid bot username")
        return v

    @field_validator("proxy")
    @classmethod
    def _proxy(cls, v):
        v = v.strip()
        if v and not v.lower().startswith(("http://", "https://", "socks5://", "socks5h://")):
            raise ValueError("proxy must be an http(s)/socks5 URL")
        return v


class DownloadSettings(_Base):
    directory: str = ""
    max_file_size_mb: int = Field(50, ge=1, le=4096)
    concurrent_downloads: int = Field(2, ge=1, le=8)
    allowed_types: list[str] = Field(default_factory=lambda: list(CATEGORIES))
    bandwidth_limit_kbps: int = Field(0, ge=0, le=10_000_000)   # 0 = unlimited
    chunk_size_kb: int = Field(256, ge=16, le=8192)
    segments: int = Field(4, ge=1, le=16)
    segment_min_mb: int = Field(8, ge=1, le=512)
    connect_timeout_s: float = Field(15.0, ge=1, le=120)
    read_timeout_s: float = Field(30.0, ge=1, le=600)
    retry_count: int = Field(3, ge=0, le=20)
    retry_backoff_s: float = Field(2.0, ge=0.1, le=300)
    auto_retry: bool = True
    auto_resume: bool = True
    min_free_disk_mb: int = Field(500, ge=0, le=1_000_000)
    max_redirects: int = Field(5, ge=0, le=10)
    verify_signature: bool = True
    block_executables: bool = True
    block_unsafe_archives: bool = True
    use_ytdlp: bool = True
    split_large_files: bool = False   # alternative when file > Bale's 50 MB upload limit
    priority_small_first: bool = False

    @field_validator("allowed_types")
    @classmethod
    def _types(cls, v):
        bad = [x for x in v if x not in CATEGORIES]
        if bad:
            raise ValueError(f"unknown file types: {bad}")
        return v


class MediaSettings(_Base):
    rename_pattern: str = ""            # e.g. "{prefix}{name}{suffix}"; empty = keep (sanitised) name
    name_prefix: str = ""
    name_suffix: str = ""
    sanitize_names: bool = True
    categorize_folders: bool = False
    make_thumbnails: bool = False
    convert_images_to: str = ""         # "", "jpg", "png", "webp"
    keep_original_until_done: bool = True
    scan_with_defender: bool = False


class PublishSettings(_Base):
    default_caption: str = "{filename}\n{filesize}"
    auto_publish: bool = True
    delete_after_upload: bool = True    # mandatory behaviour; setting exists only to make the guarantee visible
    duplicate_detection: bool = True
    send_photos_as_photo: bool = True
    send_videos_as_video: bool = True

    @field_validator("delete_after_upload")
    @classmethod
    def _must_delete(cls, v):
        # Product requirement: temp files are always removed after a successful publish.
        return True


class CleanupSettings(_Base):
    interval_min: int = Field(30, ge=1, le=1440)
    orphan_max_age_hours: int = Field(6, ge=1, le=720)
    privacy_mode: bool = False
    cleanup_on_startup: bool = True


class LoggingSettings(_Base):
    level: str = "INFO"
    retention_days: int = Field(14, ge=1, le=3650)
    db_retention_days: int = Field(90, ge=1, le=3650)
    max_db_size_mb: int = Field(500, ge=10, le=100000)
    archive_before_purge: bool = True

    @field_validator("level")
    @classmethod
    def _lvl(cls, v):
        v = v.upper()
        if v not in LOG_LEVELS:
            raise ValueError("bad log level")
        return v


class SecuritySettings(_Base):
    rate_limit_per_min: int = Field(10, ge=1, le=600)
    user_daily_quota_mb: int = Field(2048, ge=0, le=1_000_000)   # 0 = unlimited
    admin_only_default: bool = True


class NotificationSettings(_Base):
    in_app: dict[str, bool] = Field(default_factory=lambda: {e: True for e in events.NOTIFICATION_EVENTS})
    notify_admins_on_bale: bool = True
    bale_events: list[str] = Field(default_factory=lambda: [
        events.DOWNLOAD_ERROR, events.UPLOAD_ERROR, events.DISK_LOW, events.CONNECTION_ERROR])


class ApiSettings(_Base):
    enabled: bool = False                 # optional local link-intake API (127.0.0.1 only, API key required)
    port: int = Field(8765, ge=1024, le=65535)


class AppSettings(_Base):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    bale: BaleSettings = Field(default_factory=BaleSettings)
    download: DownloadSettings = Field(default_factory=DownloadSettings)
    media: MediaSettings = Field(default_factory=MediaSettings)
    publish: PublishSettings = Field(default_factory=PublishSettings)
    cleanup: CleanupSettings = Field(default_factory=CleanupSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    @model_validator(mode="after")
    def _defaults(self):
        if not self.download.directory:
            from app.core.paths import default_download_dir
            self.download.directory = str(default_download_dir())
        return self


def _deep_merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class SettingsManager:
    """Thread-safe settings holder. `update` validates first – invalid values are never saved."""

    def __init__(self, repo, bus: events.EventBus | None = None):
        self._repo, self._bus = repo, bus
        self._lock = threading.RLock()
        self._settings = AppSettings()
        self.load()

    def load(self) -> AppSettings:
        raw = self._repo.get_setting(SETTINGS_KEY)
        with self._lock:
            try:
                self._settings = AppSettings.model_validate(json.loads(raw)) if raw else AppSettings()
            except (ValueError, ValidationError):
                self._settings = AppSettings()
            return self._settings

    @property
    def settings(self) -> AppSettings:
        """Current immutable-by-convention snapshot (replaced, never mutated, by `update`) – cheap to call
        from hot loops. Callers must not modify it; use `update()`."""
        return self._settings

    def update(self, patch: dict) -> AppSettings:
        """Deep-merge `patch` into current settings, validate, persist, notify."""
        with self._lock:
            data = copy.deepcopy(self._settings.model_dump())
            _deep_merge(data, patch)
            try:
                new = AppSettings.model_validate(data)
            except ValidationError as e:
                raise ConfigError(self._fmt(e), code="config_invalid") from e
            self._settings = new
            self._repo.set_setting(SETTINGS_KEY, new.model_dump_json())
        if self._bus:
            self._bus.publish(events.SETTINGS_CHANGED, settings=new)
        return new

    def validate_patch(self, patch: dict) -> list[str]:
        """Return human-readable problems without saving anything."""
        with self._lock:
            data = copy.deepcopy(self._settings.model_dump())
        _deep_merge(data, patch)
        try:
            AppSettings.model_validate(data)
            return []
        except ValidationError as e:
            return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]

    @staticmethod
    def _fmt(e: ValidationError) -> str:
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())

    def export_json(self, path: Path) -> None:
        """Settings export. Contains no token (tokens are never part of settings)."""
        Path(path).write_text(self._settings.model_dump_json(indent=2), encoding="utf-8")

    def import_json(self, path: Path) -> AppSettings:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"cannot read settings file: {e}") from e
        # never let an imported file smuggle a path outside what the user can review in the UI
        return self.update(data)
