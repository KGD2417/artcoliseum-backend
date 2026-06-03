"""Admin control-panel aggregates: stats, artist KYC, role management."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models.user import User, Profile
from ..models.catalog import Artwork, Artist
from ..models.chat import ChatMessage
from ..models.commerce import Order, OrderItem
from ..models.site import EventRegistration, ContactMessage, SupportTicket
from ..models.competition import ArtistKyc
from ..schemas.extra import AdminArtistIn, AdminArtistOut
from ..security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


def _artist_slug(user_id: uuid.UUID) -> str:
    # Same formula artworks.create_artwork uses, so a directly-added artist and
    # one who later logs in to submit work resolve to the SAME catalog Artist.
    return f"artist-{user_id.hex[:8]}"


@router.get("/stats")
def stats(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    count = lambda model, *w: db.scalar(select(func.count()).select_from(model).where(*w)) or 0
    return {
        "pending_orders": count(Order, Order.status == "pending"),
        "unread_messages": count(ChatMessage, ChatMessage.sender == "me"),
        "event_registrations": count(EventRegistration),
        "recent_artworks": count(Artwork, Artwork.created_at >= week_ago),
        "contact_messages": count(ContactMessage),
        "open_tickets": count(SupportTicket, SupportTicket.status == "open"),
        "pending_artists": count(ArtistKyc, ArtistKyc.status == "unverified"),
    }


# Share of artwork revenue paid out to artists (COGS); the rest is platform margin.
ARTIST_PAYOUT_RATE = 0.60
PAID_STATUSES = {"paid", "shipped", "delivered"}


@router.get("/revenue")
def revenue(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Monthly profit & loss derived from paid orders.

    revenue = order totals collected; of which GST + delivery are pass-through.
    Net profit = platform margin on artwork sales (artwork sales − artist payouts).
    """
    orders = db.scalars(select(Order).order_by(Order.created_at)).all()
    months: dict[str, dict] = {}
    blank = lambda: {"orders": 0, "revenue": 0.0, "art_sales": 0.0, "gst": 0.0,
                     "delivery": 0.0, "logistics": 0.0, "payout": 0.0, "profit": 0.0}
    totals = blank()
    pending = 0
    for o in orders:
        if o.status not in PAID_STATUSES:
            if o.status == "pending":
                pending += 1
            continue
        key = o.created_at.strftime("%Y-%m")
        m = months.setdefault(key, blank())
        rev = float(o.total or 0)
        art = float(o.subtotal or 0)
        gst = float(o.tax or 0)
        delivery = float(o.delivery_fee or 0)
        logistics = rev - art - gst - delivery   # transport + setup collected
        payout = round(art * ARTIST_PAYOUT_RATE)
        profit = art - payout                    # platform margin on art
        for bucket in (m, totals):
            bucket["orders"] += 1
            bucket["revenue"] += rev
            bucket["art_sales"] += art
            bucket["gst"] += gst
            bucket["delivery"] += delivery
            bucket["logistics"] += logistics
            bucket["payout"] += payout
            bucket["profit"] += profit
    by_month = [{"month": k, **v} for k, v in sorted(months.items())]
    return {
        "payout_rate": ARTIST_PAYOUT_RATE,
        "pending_orders": pending,
        "totals": totals,
        "by_month": by_month,
    }


@router.get("/artists")
def list_artist_kyc(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(ArtistKyc).order_by(ArtistKyc.created_at.desc())).all()
    out = []
    for k in rows:
        u = db.get(User, k.user_id)
        out.append({
            "user_id": str(k.user_id), "name": k.name, "email": u.email if u else None,
            "age": k.age, "art_type": k.art_type, "location": k.location, "about": k.about,
            "status": k.status, "role": (u.profile.role if u and u.profile else "user"),
        })
    return out


@router.post("/artists/create", response_model=AdminArtistOut, status_code=201)
def create_artist(body: AdminArtistIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Add an artist directly (bypassing the competition): creates a login
    account (verified artist) AND a catalog profile shown in the Artists listing.
    The admin can then add artworks on the artist's behalf."""
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=email, password_hash=hash_password(body.password))
    user.profile = Profile(
        full_name=body.name, role="artist", artist_status="verified",
        avatar_url=body.image_url,
    )
    db.add(user)
    db.flush()  # get user.id

    slug = _artist_slug(user.id)
    db.add(Artist(
        id=slug, name=body.name, role="Art Coliseum Artist", bio=body.bio,
        image_url=body.image_url, location=body.location, age=body.age, art_type=body.art_type,
    ))
    # Mirror into KYC (verified) so the artist shows in the admin artists list.
    db.add(ArtistKyc(
        user_id=user.id, name=body.name, age=body.age, art_type=body.art_type,
        location=body.location, about=body.bio, avatar_url=body.image_url, status="verified",
    ))
    db.commit()
    return AdminArtistOut(user_id=user.id, artist_id=slug, name=body.name, email=email)


@router.post("/artists/{user_id}/verify")
def verify_artist(user_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Admin shortcut to verify an artist without the competition (e.g. direct invite)."""
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == user_id))
    if kyc:
        kyc.status = "verified"
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if prof:
        prof.artist_status = "verified"
        prof.role = "artist"
    db.commit()
    return {"ok": True}


@router.patch("/profiles/{user_id}/role")
def set_role(user_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    role = body.get("role")
    if role not in {"user", "artist", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    prof.role = role
    if role == "admin":
        prof.is_admin = True
    db.commit()
    return {"ok": True, "role": role}
