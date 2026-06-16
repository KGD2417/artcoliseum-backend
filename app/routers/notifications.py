"""In-app notification feed (per-user bell)."""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.notification import Notification
from ..utils import notify

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {
        "id": str(n.id), "type": n.type, "title": n.title, "body": n.body,
        "link": n.link, "read": n.read, "created_at": n.created_at.isoformat(),
    }


@router.get("")
def my_notifications(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    rows = db.scalars(
        select(Notification).where(Notification.user_id == me.id)
        .order_by(Notification.created_at.desc()).limit(50)
    ).all()
    return [_out(n) for n in rows]


@router.get("/unread")
def unread_count(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    n = db.scalar(
        select(func.count()).where(Notification.user_id == me.id, Notification.read.is_(False))
    ) or 0
    return {"unread": n}


@router.post("/read")
def mark_all_read(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    db.execute(
        update(Notification).where(Notification.user_id == me.id, Notification.read.is_(False)).values(read=True)
    )
    db.commit()
    return {"ok": True}


@router.post("/{notification_id}/read")
def mark_one_read(notification_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != me.id:
        raise HTTPException(status_code=404, detail="Not found")
    n.read = True
    db.commit()
    return {"ok": True}


@router.post("/cron/deadlines")
def run_deadline_reminders(db: Session = Depends(get_db), x_cron_secret: str | None = Header(default=None)):
    """Notify verified artists about exhibitions whose registration ends soon.
    Call daily (Railway cron) with header `X-Cron-Secret: <CRON_SECRET>`."""
    from datetime import datetime, timedelta, timezone
    from ..models.exhibition import Exhibition

    if not settings.CRON_SECRET or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(status_code=403, detail="Bad cron secret")

    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=3)
    exhibitions = db.scalars(
        select(Exhibition).where(
            Exhibition.registration_ends_at.is_not(None),
            Exhibition.registration_ends_at > now,
            Exhibition.registration_ends_at <= soon,
        )
    ).all()
    artist_ids = notify.verified_artist_user_ids(db)
    sent = 0
    for ex in exhibitions:
        days = max(0, (ex.registration_ends_at - now).days)
        # Avoid re-sending the same reminder within ~20h (cron may run >1×/day).
        already = db.scalar(
            select(func.count()).where(
                Notification.type == "exhibition",
                Notification.link == "/exhibition",
                Notification.title.ilike(f"%{ex.title}%"),
                Notification.created_at > now - timedelta(hours=20),
            )
        ) or 0
        if already:
            continue
        sent += notify.create_many(
            db, artist_ids, type="exhibition",
            title=f'"{ex.title}" registration closes in {days} day{"s" if days != 1 else ""}',
            body="Submit your work before registration closes.",
            link="/exhibition",
        )
    return {"ok": True, "exhibitions": len(exhibitions), "notifications_sent": sent}
