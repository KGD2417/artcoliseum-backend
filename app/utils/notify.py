"""Create in-app notifications + small lookup helpers.

`create()` persists a notification (shown via the bell on next fetch/poll).
Async callers can additionally `await ping()` to push a live websocket refresh.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, cast, String, func
from sqlalchemy.orm import Session

from ..models.notification import Notification
from ..models.user import User, Profile
from ..websocket import manager


def create(db: Session, user_id, *, type: str, title: str, body: str | None = None, link: str | None = None) -> Notification:
    n = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    db.add(n)
    db.commit()
    return n


def create_many(db: Session, user_ids, *, type: str, title: str, body: str | None = None, link: str | None = None) -> int:
    n = 0
    for uid in set(user_ids):
        if uid:
            db.add(Notification(user_id=uid, type=type, title=title, body=body, link=link))
            n += 1
    if n:
        db.commit()
    return n


async def ping(user_ids) -> None:
    """Live nudge so open tabs refetch their bell immediately."""
    ids = {str(u) for u in user_ids if u}
    if ids:
        await manager.broadcast({"type": "notification"}, ids, notify_admins=False)


def admin_user_ids(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(Profile.user_id).where(Profile.role == "admin")))


def verified_artist_user_ids(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(Profile.user_id).where(Profile.artist_status == "verified")))


def artist_user_for_slug(db: Session, artist_slug: str | None) -> User | None:
    """Map an artwork's artist_id slug ('artist-xxxxxxxx') back to its User."""
    if not artist_slug or not artist_slug.startswith("artist-"):
        return None
    hex8 = artist_slug.split("artist-", 1)[1][:8]
    if len(hex8) < 8:
        return None
    return db.scalar(
        select(User).where(func.left(func.replace(cast(User.id, String), "-", ""), 8) == hex8)
    )
