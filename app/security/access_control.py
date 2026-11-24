"""RBAC, per-user rate limiting and daily quota checks."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from enum import IntEnum

from app.core.exceptions import AccessDenied, RateLimited


class Role(IntEnum):
    READ_ONLY = 1
    OPERATOR = 2
    ADMIN = 3
    SUPER_ADMIN = 4

    @classmethod
    def parse(cls, value: "str | int | Role") -> "Role":
        if isinstance(value, Role):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper().replace(" ", "_")]


# permission -> minimum role
PERMISSIONS: dict[str, Role] = {
    "view_status": Role.READ_ONLY,
    "submit_link": Role.OPERATOR,
    "control_queue": Role.OPERATOR,
    "cancel_any": Role.ADMIN,
    "view_logs": Role.ADMIN,
    "manage_channels": Role.ADMIN,
    "manage_settings": Role.ADMIN,
    "manage_users": Role.ADMIN,
    "manage_admins": Role.SUPER_ADMIN,
    "backup_restore": Role.SUPER_ADMIN,
}

LOCAL_USER_ID = 0  # the person operating the desktop app


class AccessController:
    def __init__(self, repo):
        self._repo = repo

    def get_role(self, user_id: int) -> Role | None:
        if user_id == LOCAL_USER_ID:
            return Role.SUPER_ADMIN
        u = self._repo.get_user(user_id)
        if u is None or u["blocked"]:
            return None
        return Role.parse(u["role"])

    def is_authorized(self, user_id: int, permission: str) -> bool:
        role = self.get_role(user_id)
        return role is not None and role >= PERMISSIONS[permission]

    def require(self, user_id: int, permission: str) -> Role:
        role = self.get_role(user_id)
        if role is None:
            raise AccessDenied("user is not authorised", code="not_authorized")
        if role < PERMISSIONS[permission]:
            raise AccessDenied(f"role {role.name} lacks {permission}", code="insufficient_role")
        return role

    def can_assign(self, actor_id: int, new_role: Role) -> bool:
        actor = self.get_role(actor_id)
        if actor is None:
            return False
        if new_role >= Role.ADMIN:
            return actor >= Role.SUPER_ADMIN
        return actor >= Role.ADMIN


class RateLimiter:
    """Sliding-window limiter: at most `limit` events per `window` seconds per key."""

    def __init__(self, limit: int = 20, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def configure(self, limit: int) -> None:
        self.limit = limit

    def check(self, key: int) -> None:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise RateLimited("too many requests", code="rate_limited")
            q.append(now)
