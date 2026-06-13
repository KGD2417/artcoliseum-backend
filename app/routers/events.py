"""Events + registrations (public read/register, admin CRUD)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_optional_user, get_current_user, require_role
from ..models.user import User
from ..models.site import Event, EventRegistration
from ..schemas.extra import EventOut, EventRegistrationIn

router = APIRouter(prefix="/events", tags=["events"])


def _parse_dt(v):
    """Accept an ISO string (incl. trailing 'Z') or datetime → aware datetime, else None."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _event_status(ev: Event) -> str:
    """Derive upcoming | ongoing | past from the event's dates (live, by 'now').
    Falls back to the stored status when an event has no dates set."""
    now = datetime.now(timezone.utc)
    s, e = ev.starts_at, ev.ends_at
    # Normalise any naive datetimes to UTC so comparisons never crash.
    if s and s.tzinfo is None:
        s = s.replace(tzinfo=timezone.utc)
    if e and e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)
    if s and now < s:
        return "upcoming"
    if e and now > e:
        return "past"
    if s and not e:
        return "ongoing" if now >= s else "upcoming"
    if e and not s:
        return "past" if now > e else "ongoing"
    if s and e:
        return "ongoing"
    return ev.status or "upcoming"


def _out(ev: Event) -> EventOut:
    """Serialise an event with its status derived live from the dates."""
    o = EventOut.model_validate(ev)
    o.status = _event_status(ev)
    return o


@router.get("", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)):
    rows = db.scalars(select(Event).order_by(Event.starts_at)).all()
    return [_out(ev) for ev in rows]


@router.get("/registrations/mine", response_model=list[EventOut])
def my_registrations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The events the signed-in user has registered for (for their dashboard)."""
    ev_ids = db.scalars(
        select(EventRegistration.event_id).where(EventRegistration.user_id == me.id)
    ).all()
    if not ev_ids:
        return []
    rows = db.scalars(select(Event).where(Event.id.in_(ev_ids)).order_by(Event.starts_at)).all()
    return [_out(ev) for ev in rows]


@router.post("", response_model=EventOut, status_code=201)
def create_event(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ev = Event(
        title=body.get("title", "Untitled"), description=body.get("description"),
        location=body.get("location"),
        curator=body.get("curator"), image_url=body.get("image_url"),
        starts_at=_parse_dt(body.get("starts_at")), ends_at=_parse_dt(body.get("ends_at")),
        address=body.get("address"), parking=body.get("parking"),
        maps_url=body.get("maps_url"), details=body.get("details"),
    )
    ev.status = _event_status(ev)  # derived from the dates, not chosen
    db.add(ev); db.commit(); db.refresh(ev)
    return _out(ev)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    # status is never set by the client — it is derived from the dates below.
    for f in ("title", "description", "location", "curator", "image_url", "starts_at", "ends_at", "address", "parking", "maps_url", "details"):
        if f in body and body[f] is not None:
            setattr(ev, f, _parse_dt(body[f]) if f in ("starts_at", "ends_at") else body[f])
    ev.status = _event_status(ev)
    db.commit(); db.refresh(ev)
    return _out(ev)


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ev = db.get(Event, event_id)
    if ev:
        db.delete(ev); db.commit()
    return None


@router.post("/{event_id}/register", status_code=201)
def register(event_id: uuid.UUID, body: EventRegistrationIn, db: Session = Depends(get_db), me: User | None = Depends(get_optional_user)):
    if not db.get(Event, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
    # Don't let a signed-in user register for the same event twice.
    if me:
        existing = db.scalar(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == me.id,
            )
        )
        if existing:
            return {"ok": True, "already_registered": True}
    db.add(EventRegistration(
        event_id=event_id, user_id=(me.id if me else None),
        name=body.name, email=body.email, phone=body.phone, message=body.message,
    ))
    db.commit()
    return {"ok": True}


@router.get("/{event_id}/registrations")
def list_registrations(event_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(EventRegistration).where(EventRegistration.event_id == event_id)).all()
    return [{"name": r.name, "email": r.email, "phone": r.phone, "message": r.message} for r in rows]
