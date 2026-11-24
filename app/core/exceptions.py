"""Application exception hierarchy."""


class HubError(Exception):
    """Base error. `code` is a stable machine-readable key used for localisation."""
    code = "error"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message or self.code)
        if code:
            self.code = code


class ConfigError(HubError):
    code = "config_invalid"


class SecurityError(HubError):
    code = "security_blocked"


class UrlBlockedError(SecurityError):
    code = "url_blocked"


class AccessDenied(SecurityError):
    code = "access_denied"


class RateLimited(SecurityError):
    code = "rate_limited"


class DownloadError(HubError):
    code = "download_failed"


class FileTooLarge(DownloadError):
    code = "file_too_large"


class NotDownloadable(DownloadError):
    code = "not_downloadable"


class JobCancelled(HubError):
    code = "cancelled"


class JobPaused(HubError):
    code = "paused"


class DiskSpaceLow(DownloadError):
    code = "disk_space_low"


class BaleApiError(HubError):
    code = "bale_api_error"

    def __init__(self, message: str = "", error_code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after


class BaleAuthError(BaleApiError):
    code = "bale_auth_error"


class BaleNetworkError(BaleApiError):
    code = "bale_network_error"


class PublishError(HubError):
    code = "publish_failed"


class BackupError(HubError):
    code = "backup_failed"
