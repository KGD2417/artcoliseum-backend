"""Delivery tracking (admin-updatable, Blue-Dart style) + delivery OTP."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.catalog import Artwork
from ..models.commerce import Order, OrderItem, Delivery, DeliveryEvent, DeliveryOTP
from ..models.review import OwnedArtwork
from ..schemas.commerce import DeliveryOut, StageUpdateIn, OtpConfirmIn
from ..security import generate_otp
from ..utils import pricing, notify
from ..websocket import manager

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.get("/estimate")
def estimate(pincode: str | None = None):
    """Public: shipping zone + ETA window + delivery fee for a destination PIN,
    plus the vault address for self-pickup."""
    est = pricing.delivery_estimate(pincode)
    est["vault"] = pricing.VAULT
    return est

STAGES = ["order_confirmed", "curation_crating", "dispatched", "out_for_delivery", "installation", "delivered"]
STAGE_INFO = {
    "order_confirmed": ("Order Confirmed", "Payment received. Curator assigned."),
    "curation_crating": ("Curation & Crating", "Climate-controlled crate sealed at our vault."),
    "dispatched": ("Dispatched", "Handed to Blue Dart logistics."),
    "out_for_delivery": ("Out for Delivery", "On the way to your delivery address."),
    "installation": ("Final Installation", "Our white-glove team is installing your piece."),
    "delivered": ("Delivered", "Artwork received and confirmed by you."),
}


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _with_events(db: Session, d: Delivery) -> Delivery:
    d.events = db.scalars(
        select(DeliveryEvent).where(DeliveryEvent.delivery_id == d.id).order_by(DeliveryEvent.created_at)
    ).all()
    return d


def _grant_physical(db: Session, order: Order):
    """Create physical-ownership rows once receipt is confirmed (OTP) — for both
    delivered and self-collected pieces."""
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    for it in items:
        exists = db.scalar(
            select(OwnedArtwork).where(
                OwnedArtwork.order_id == order.id,
                OwnedArtwork.artwork_id == it.artwork_id,
                OwnedArtwork.kind == "physical",
            )
        )
        if not exists:
            db.add(OwnedArtwork(user_id=order.user_id, artwork_id=it.artwork_id, order_id=order.id, kind="physical"))


@router.get("/by-order/{order_id}", response_model=DeliveryOut)
def by_order(order_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    is_admin = bool(me.profile and me.profile.role == "admin")
    if order.user_id != me.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not your order")
    d = db.scalar(select(Delivery).where(Delivery.order_id == order_id))
    if not d:
        raise HTTPException(status_code=404, detail="No delivery yet")
    return _with_events(db, d)


@router.patch("/{delivery_id}/stage")
async def update_stage(delivery_id: uuid.UUID, body: StageUpdateIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    if body.stage not in STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    d = db.get(Delivery, delivery_id)
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    d.stage = body.stage
    if body.current_location:
        d.current_location = body.current_location
    if body.eta:
        d.eta = body.eta
    title, default_detail = STAGE_INFO.get(body.stage, (body.stage, None))
    db.add(DeliveryEvent(delivery_id=d.id, stage=body.stage, title=title, detail=body.detail or default_detail))

    order = db.get(Order, d.order_id)
    if body.stage in ("dispatched", "out_for_delivery"):
        order.status = "shipped"

    # Issue a fresh receipt OTP once the piece is out for delivery / being installed
    # (whichever the courier reaches first), if one isn't already live.
    otp_code = None
    if body.stage in ("out_for_delivery", "installation"):
        live = db.scalar(
            select(DeliveryOTP).where(
                DeliveryOTP.delivery_id == d.id, DeliveryOTP.consumed_at.is_(None)
            ).order_by(DeliveryOTP.created_at.desc())
        )
        if not live or live.expires_at < datetime.now(timezone.utc):
            otp_code = generate_otp()
            db.add(DeliveryOTP(
                delivery_id=d.id, code_hash=_hash(otp_code),
                expires_at=datetime.now(timezone.utc) + timedelta(days=3),
            ))

    db.commit()
    db.refresh(d)
    # notify the buyer so their tracking view refreshes
    await manager.broadcast(
        {"type": "delivery", "order_id": str(d.order_id), "stage": d.stage},
        {str(order.user_id)} if order.user_id else set(),
    )
    # Persistent bell notification for the buyer.
    if order.user_id:
        notify.create(
            db, order.user_id, type="delivery",
            title=f"Order update: {title}",
            body=(body.detail or default_detail or ""),
            link="/profile",
        )
        await notify.ping([order.user_id])
    return {"delivery": DeliveryOut.model_validate(_with_events(db, d)).model_dump(), "otp": otp_code}


@router.post("/{delivery_id}/otp")
def generate_delivery_otp(delivery_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    d = db.get(Delivery, delivery_id)
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    code = generate_otp()
    db.add(DeliveryOTP(delivery_id=d.id, code_hash=_hash(code), expires_at=datetime.now(timezone.utc) + timedelta(days=2)))
    db.commit()
    return {"otp": code}  # dummy: returned so admin can relay it


@router.post("/{delivery_id}/confirm", response_model=DeliveryOut)
def confirm_delivery(delivery_id: uuid.UUID, body: OtpConfirmIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    d = db.get(Delivery, delivery_id)
    if not d:
        raise HTTPException(status_code=404, detail="Delivery not found")
    order = db.get(Order, d.order_id)
    if not order or order.user_id != me.id:
        raise HTTPException(status_code=403, detail="Not your delivery")

    otp = db.scalar(
        select(DeliveryOTP).where(DeliveryOTP.delivery_id == d.id, DeliveryOTP.consumed_at.is_(None))
        .order_by(DeliveryOTP.created_at.desc())
    )
    now = datetime.now(timezone.utc)
    if not otp or otp.code_hash != _hash(body.code.strip()) or otp.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    otp.consumed_at = now
    d.stage = "delivered"
    db.add(DeliveryEvent(delivery_id=d.id, stage="delivered", title="Delivered", detail="Receipt confirmed via OTP."))
    order.status = "delivered"
    _grant_physical(db, order)
    db.commit()
    db.refresh(d)
    return _with_events(db, d)
