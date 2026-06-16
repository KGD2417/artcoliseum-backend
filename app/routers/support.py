"""Contact form + support tickets (public submit, admin manage)."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_optional_user, require_role
from ..models.user import User
from ..models.site import ContactMessage, SupportTicket
from ..schemas.extra import ContactIn, TicketIn
from ..utils import email

router = APIRouter(tags=["support"])


def _alert(bg: BackgroundTasks, kind: str, body) -> None:
    """Queue an admin email for a new contact/support submission (no-op if SMTP
    isn't configured). Runs after the response so it never blocks the submit."""
    lines = [
        f"New {kind} from {body.name or 'someone'}",
        f"Email: {body.email or '—'}",
        f"Phone: {body.phone or '—'}",
        f"Subject: {body.subject or '—'}",
        "",
        body.message or "",
    ]
    bg.add_task(
        email.notify_admin,
        f"[Art Coliseum] New {kind}: {body.subject or (body.name or 'message')}",
        "\n".join(lines),
        reply_to=body.email or None,
    )


@router.post("/contact", status_code=201)
def contact(body: ContactIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    db.add(ContactMessage(
        name=body.name, email=body.email, phone=body.phone, subject=body.subject, message=body.message,
        images=body.images or [], videos=body.videos or [],
    ))
    db.commit()
    _alert(bg, "contact message", body)
    return {"ok": True}


@router.get("/contact")
def list_contact(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(ContactMessage).order_by(ContactMessage.created_at.desc())).all()
    return [{"id": str(r.id), "name": r.name, "email": r.email, "phone": r.phone, "subject": r.subject, "message": r.message,
             "images": r.images or [], "videos": r.videos or [], "created_at": r.created_at.isoformat()} for r in rows]


@router.post("/support/tickets", status_code=201)
def create_ticket(body: TicketIn, bg: BackgroundTasks, db: Session = Depends(get_db), me: User | None = Depends(get_optional_user)):
    db.add(SupportTicket(
        user_id=(me.id if me else None), name=body.name, email=body.email, phone=body.phone, subject=body.subject, message=body.message,
        images=body.images or [], videos=body.videos or [],
    ))
    db.commit()
    _alert(bg, "support ticket", body)
    return {"ok": True}


@router.get("/support/tickets")
def list_tickets(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(SupportTicket).order_by(SupportTicket.created_at.desc())).all()
    return [{"id": str(r.id), "name": r.name, "email": r.email, "phone": r.phone, "subject": r.subject, "message": r.message,
             "status": r.status, "images": r.images or [], "videos": r.videos or [], "created_at": r.created_at.isoformat()} for r in rows]


@router.patch("/support/tickets/{ticket_id}")
def set_ticket_status(ticket_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    t = db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if body.get("status"):
        t.status = body["status"]
    db.commit()
    return {"ok": True, "status": t.status}
