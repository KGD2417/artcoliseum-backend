"""Events + registrations (public read/register, admin CRUD)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_optional_user, get_current_user, require_role
from ..models.user import User
from ..models.site import Event, EventRegistration
from ..schemas.extra import EventOut, EventRegistrationIn

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)):
    return list(db.scalars(select(Event).order_by(Event.starts_at)).all())


@router.get("/registrations/mine", response_model=list[EventOut])
def my_registrations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The events the signed-in user has registered for (for their dashboard)."""
    ev_ids = db.scalars(
        select(EventRegistration.event_id).where(EventRegistration.user_id == me.id)
    ).all()
    if not ev_ids:
        return []
    return list(db.scalars(select(Event).where(Event.id.in_(ev_ids)).order_by(Event.starts_at)).all())


@router.post("", response_model=EventOut, status_code=201)
def create_event(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ev = Event(
        title=body.get("title", "Untitled"), description=body.get("description"),
        status=body.get("status", "upcoming"), location=body.get("location"),
        curator=body.get("curator"), image_url=body.get("image_url"),
        starts_at=body.get("starts_at"), ends_at=body.get("ends_at"),
        address=body.get("address"), parking=body.get("parking"), details=body.get("details"),
    )
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ev = db.get(Event, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    for f in ("title", "description", "status", "location", "curator", "image_url", "starts_at", "ends_at", "address", "parking", "details"):
        if f in body and body[f] is not None:
            setattr(ev, f, body[f])
    db.commit(); db.refresh(ev)
    return ev


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
