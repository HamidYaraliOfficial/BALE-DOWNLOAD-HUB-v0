"""Shared enums/constants."""
from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    WAITING = "waiting"
    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLEANUP = "cleanup"


ACTIVE_STATUSES = (JobStatus.VALIDATING.value, JobStatus.DOWNLOADING.value, JobStatus.PROCESSING.value,
                   JobStatus.UPLOADING.value, JobStatus.CLEANUP.value)
PENDING_STATUSES = (JobStatus.WAITING.value, JobStatus.PAUSED.value)
TERMINAL_STATUSES = (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)
LIVE_STATUSES = ACTIVE_STATUSES + PENDING_STATUSES

CATEGORIES = ("image", "video", "audio", "document", "archive", "other")

# Limits taken from the official Bale Bot API documentation (docs.bale.ai).
BALE_MAX_UPLOAD_BYTES = 50 * 1024 * 1024      # multipart upload, non-photo files
BALE_MAX_PHOTO_BYTES = 10 * 1024 * 1024       # multipart upload, photos
BALE_MAX_CAPTION = 1024
BALE_MAX_TEXT = 4096
BALE_MAX_GETFILE_BYTES = 20 * 1024 * 1024
