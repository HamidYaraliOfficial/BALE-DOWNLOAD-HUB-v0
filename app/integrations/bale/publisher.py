"""Chooses the right Bale send method for a file and handles documented fall-backs."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

from app.core.constants import BALE_MAX_PHOTO_BYTES, BALE_MAX_UPLOAD_BYTES
from app.core.exceptions import BaleApiError, BaleAuthError, BaleNetworkError, PublishError
from app.integrations.bale.adapter import BaleAPIAdapter

log = logging.getLogger(__name__)

PHOTO_EXT = {".jpg", ".jpeg", ".png"}
VIDEO_EXT = {".mp4", ".m4v"}                 # docs: "Bale clients support MPEG4 videos"
AUDIO_EXT = {".mp3", ".m4a"}                 # docs: sendAudio needs .MP3 or .M4A


@dataclass
class SendResult:
    method: str
    message_id: int
    fell_back: bool = False


def choose_method(path: str, category: str, size: int, photos_as_photo: bool = True,
                  videos_as_video: bool = True) -> str:
    ext = os.path.splitext(path)[1].lower()
    if category == "image" and ext in PHOTO_EXT and photos_as_photo and size <= BALE_MAX_PHOTO_BYTES:
        return "sendPhoto"
    if category == "video" and ext in VIDEO_EXT and videos_as_video and size <= BALE_MAX_UPLOAD_BYTES:
        return "sendVideo"
    if category == "audio" and ext in AUDIO_EXT and size <= BALE_MAX_UPLOAD_BYTES:
        return "sendAudio"
    return "sendDocument"


class BalePublisher:
    def __init__(self, adapter: BaleAPIAdapter, photos_as_photo: bool = True, videos_as_video: bool = True):
        self._a = adapter
        self._photo, self._video = photos_as_photo, videos_as_video

    def send(self, chat_id: str | int, path: str, category: str, caption: str | None,
             progress: Callable[[int, int], None] | None = None) -> SendResult:
        size = os.path.getsize(path)
        if size > BALE_MAX_UPLOAD_BYTES:
            raise PublishError(f"file is {size} bytes; Bale bots can upload at most {BALE_MAX_UPLOAD_BYTES}",
                               code="too_large_for_bale")
        method = choose_method(path, category, size, self._photo, self._video)
        senders = {"sendPhoto": self._a.send_photo, "sendVideo": self._a.send_video,
                   "sendAudio": self._a.send_audio, "sendDocument": self._a.send_document}
        try:
            mid = senders[method](chat_id, path, caption, progress)
            return SendResult(method, mid)
        except (BaleAuthError, BaleNetworkError):
            raise
        except BaleApiError as e:
            if method == "sendDocument":
                raise
            log.info("%s rejected (%s) – falling back to sendDocument", method, e)
            mid = self._a.send_document(chat_id, path, caption, progress)
            return SendResult("sendDocument", mid, fell_back=True)
