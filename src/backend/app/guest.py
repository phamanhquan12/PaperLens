"""Anonymous guest trial sessions and hard usage quotas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.models import GuestSession
from app.db.session import session_scope

QuotaKind = Literal["queries", "papers", "images"]
GUEST_TOKEN_PREFIX = "guest."


@dataclass(frozen=True)
class GuestQuotaSnapshot:
    queries_used: int
    papers_used: int
    images_used: int
    queries_limit: int
    papers_limit: int
    images_limit: int
    expires_at: datetime

    @property
    def queries_remaining(self) -> int:
        return max(0, self.queries_limit - self.queries_used)

    @property
    def papers_remaining(self) -> int:
        return max(0, self.papers_limit - self.papers_used)

    @property
    def images_remaining(self) -> int:
        return max(0, self.images_limit - self.images_used)

    def as_dict(self) -> dict[str, int | str]:
        return {
            "queries_used": self.queries_used,
            "papers_used": self.papers_used,
            "images_used": self.images_used,
            "queries_limit": self.queries_limit,
            "papers_limit": self.papers_limit,
            "images_limit": self.images_limit,
            "queries_remaining": self.queries_remaining,
            "papers_remaining": self.papers_remaining,
            "images_remaining": self.images_remaining,
            "expires_at": self.expires_at.isoformat(),
        }


def guest_trial_available(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.auth_enabled and cfg.guest_trial_enabled)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _snapshot(row: GuestSession, settings: Settings) -> GuestQuotaSnapshot:
    return GuestQuotaSnapshot(
        queries_used=int(row.queries_used or 0),
        papers_used=int(row.papers_used or 0),
        images_used=int(row.images_used or 0),
        queries_limit=settings.guest_max_queries,
        papers_limit=settings.guest_max_papers,
        images_limit=settings.guest_max_images,
        expires_at=_ensure_aware(row.expires_at),
    )


def _quota_error(kind: QuotaKind, snapshot: GuestQuotaSnapshot) -> HTTPException:
    labels = {
        "queries": ("query", snapshot.queries_limit, snapshot.queries_remaining),
        "papers": ("paper upload", snapshot.papers_limit, snapshot.papers_remaining),
        "images": ("image upload", snapshot.images_limit, snapshot.images_remaining),
    }
    label, limit, remaining = labels[kind]
    return HTTPException(
        status_code=429,
        detail={
            "error": "guest_quota_exceeded",
            "message": (
                f"Guest trial {label} limit reached ({limit}). "
                "Create a free account to continue."
            ),
            "quota": snapshot.as_dict(),
            "kind": kind,
            "remaining": remaining,
        },
    )


def create_guest_session(settings: Settings | None = None) -> tuple[str, str, GuestQuotaSnapshot]:
    """Create a browser-bound guest session and return (access_token, user_id, quota)."""
    cfg = settings or get_settings()
    if not guest_trial_available(cfg):
        raise HTTPException(status_code=404, detail="Guest trial is not available")

    session_id = str(uuid4())
    user_id = f"guest-{session_id}"
    expires_at = _utcnow() + timedelta(hours=max(1, cfg.guest_session_ttl_hours))
    with session_scope(cfg) as session:
        row = GuestSession(
            id=session_id,
            user_id=user_id,
            queries_used=0,
            papers_used=0,
            images_used=0,
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        snapshot = _snapshot(row, cfg)
    return f"{GUEST_TOKEN_PREFIX}{session_id}", user_id, snapshot


def resolve_guest_token(
    token: str, *, settings: Settings | None = None
) -> tuple[str, GuestQuotaSnapshot] | None:
    """Return (user_id, quota) for a valid guest bearer token, else None."""
    cfg = settings or get_settings()
    if not token.startswith(GUEST_TOKEN_PREFIX):
        return None
    if not guest_trial_available(cfg):
        raise HTTPException(status_code=401, detail="Guest trial is disabled")
    session_id = token[len(GUEST_TOKEN_PREFIX) :].strip()
    if not session_id:
        return None
    with session_scope(cfg) as session:
        row = session.get(GuestSession, session_id)
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid guest session")
        if _ensure_aware(row.expires_at) <= _utcnow():
            raise HTTPException(status_code=401, detail="Guest session expired")
        return row.user_id, _snapshot(row, cfg)


def get_guest_quota(user_id: str, *, settings: Settings | None = None) -> GuestQuotaSnapshot:
    cfg = settings or get_settings()
    with session_scope(cfg) as session:
        row = session.scalar(select(GuestSession).where(GuestSession.user_id == user_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Guest session not found")
        if _ensure_aware(row.expires_at) <= _utcnow():
            raise HTTPException(status_code=401, detail="Guest session expired")
        return _snapshot(row, cfg)


def consume_guest_quota(
    user_id: str,
    *,
    settings: Settings | None = None,
    queries: int = 0,
    papers: int = 0,
    images: int = 0,
) -> GuestQuotaSnapshot:
    """Atomically reserve guest quota before expensive work. Raises 429 when exhausted."""
    cfg = settings or get_settings()
    if queries < 0 or papers < 0 or images < 0:
        raise ValueError("Quota deltas must be non-negative")
    with session_scope(cfg) as session:
        row = session.scalar(
            select(GuestSession).where(GuestSession.user_id == user_id)
        )
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid guest session")
        if _ensure_aware(row.expires_at) <= _utcnow():
            raise HTTPException(status_code=401, detail="Guest session expired")

        snapshot = _snapshot(row, cfg)
        if queries and snapshot.queries_remaining < queries:
            raise _quota_error("queries", snapshot)
        if papers and snapshot.papers_remaining < papers:
            raise _quota_error("papers", snapshot)
        if images and snapshot.images_remaining < images:
            raise _quota_error("images", snapshot)

        row.queries_used = int(row.queries_used or 0) + queries
        row.papers_used = int(row.papers_used or 0) + papers
        row.images_used = int(row.images_used or 0) + images
        session.add(row)
        session.flush()
        return _snapshot(row, cfg)
