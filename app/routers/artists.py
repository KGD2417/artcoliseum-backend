"""Public artist listing + profile, artist KYC onboarding, and the artist sales
dashboard (orders of their work + direct fulfillment)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artist, Artwork
from ..models.commerce import Order, OrderItem, Delivery, DeliveryEvent
from ..models.competition import ArtistKyc
from ..schemas.catalog import ArtistOut, ArtworkOut
from ..schemas.commerce import ArtistOrderOut, PickupAddressIn, DispatchIn
from ..schemas.extra import KycIn, ArtistStatusOut
from ..utils import shipping

router = APIRouter(prefix="/artists", tags=["artists"])


@router.post("/apply", response_model=ArtistStatusOut)
def apply_artist(body: KycIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Submit artist KYC → become a PENDING artist, awaiting admin approval."""
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
    if kyc:
        kyc.name = body.name; kyc.age = body.age; kyc.art_type = body.art_type
        kyc.location = body.location; kyc.about = body.about; kyc.avatar_url = body.avatar_url
        kyc.gender = body.gender
        if kyc.status not in ("verified",):
            kyc.status = "pending"
            kyc.rejection_reason = None  # fresh application clears the old decline note
    else:
        db.add(ArtistKyc(
            user_id=me.id, name=body.name, age=body.age, art_type=body.art_type,
            location=body.location, about=body.about, avatar_url=body.avatar_url,
            gender=body.gender, status="pending",
        ))
    # none/unverified/rejected → pending (awaiting approval). Never downgrade a verified artist.
    if me.profile and me.profile.artist_status in ("none", "unverified", "rejected"):
        me.profile.artist_status = "pending"
    db.commit()
    return ArtistStatusOut(
        artist_status=me.profile.artist_status if me.profile else "pending",
        role=me.profile.role if me.profile else "user",
    )


@router.get("/me/status", response_model=ArtistStatusOut)
def my_status(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    status = me.profile.artist_status if me.profile else "none"
    reason = None
    if status == "rejected":
        kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
        reason = kyc.rejection_reason if kyc else None
    return ArtistStatusOut(
        artist_status=status,
        role=me.profile.role if me.profile else "user",
        rejection_reason=reason,
    )


def _my_artist_slug(me: User) -> str:
    return f"artist-{me.id.hex[:8]}"


@router.get("/me/profile", response_model=ArtistOut)
def my_artist_profile(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The artist's public catalog profile (derived from KYC if not yet persisted)."""
    artist = db.get(Artist, _my_artist_slug(me))
    if artist:
        return artist
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
    # Transient (not persisted) so empty profiles don't appear in the public listing.
    return Artist(
        id=_my_artist_slug(me),
        name=(kyc.name if kyc else (me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0])),
        role="Art Coliseum Artist",
        bio=(kyc.about if kyc else None), image_url=(kyc.avatar_url if kyc else None),
        location=(kyc.location if kyc else None), age=(kyc.age if kyc else None),
        art_type=(kyc.art_type if kyc else None), gender=(kyc.gender if kyc else None),
    )


@router.patch("/me/profile", response_model=ArtistOut)
def update_my_artist_profile(body: dict, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Verified artist edits their public profile (name, bio, photo, location, art_type)."""
    if not (me.profile and me.profile.artist_status == "verified"):
        raise HTTPException(status_code=403, detail="Only approved artists may edit a profile")
    slug = _my_artist_slug(me)
    artist = db.get(Artist, slug)
    if not artist:
        artist = Artist(id=slug, name=(me.profile.full_name or me.email.split("@")[0]), role="Art Coliseum Artist")
        db.add(artist)
    for field in ("name", "bio", "image_url", "location", "art_type", "age", "gender"):
        if field in body and body[field] is not None:
            setattr(artist, field, body[field])
    # Mirror onto KYC so the admin list and onboarding data stay consistent.
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
    if kyc:
        kyc.name = artist.name; kyc.about = artist.bio; kyc.avatar_url = artist.image_url
        kyc.location = artist.location; kyc.art_type = artist.art_type
        kyc.age = artist.age; kyc.gender = artist.gender
    db.commit(); db.refresh(artist)
    return artist


# ── Artist sales dashboard ─────────────────────────────────────────────────────
@router.get("/me/pickup-address")
def get_pickup_address(me: User = Depends(get_current_user)):
    """The artist's ship-from address (origin for direct fulfillment)."""
    return (me.profile.pickup_address if me.profile else None) or {}


@router.put("/me/pickup-address")
def set_pickup_address(body: PickupAddressIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if not me.profile:
        raise HTTPException(status_code=400, detail="Profile not found")
    addr = body.model_dump()
    # Preserve any previously-registered Shiprocket nickname unless the address
    # materially changed (then it must be re-registered on next dispatch).
    prev = me.profile.pickup_address or {}
    same_place = all(prev.get(k) == addr.get(k) for k in ("line1", "city", "zip"))
    if same_place and prev.get("sr_nickname"):
        addr["sr_nickname"] = prev["sr_nickname"]
    me.profile.pickup_address = addr
    db.commit()
    return addr


def _artist_order_out(db: Session, it: OrderItem, order: Order, delivery: Delivery | None) -> ArtistOrderOut:
    art = db.get(Artwork, it.artwork_id) if it.artwork_id else None
    is_custom = bool(it.options or it.custom_width or it.custom_height or it.custom_depth)
    return ArtistOrderOut(
        order_item_id=it.id, order_id=order.id, artwork_id=it.artwork_id,
        title=it.title or (art.title if art else None),
        image=(art.images[0] if art and art.images else None),
        price=it.price, qty=it.qty, fulfillment=it.fulfillment,
        is_custom=is_custom, options=it.options,
        custom_width=it.custom_width, custom_height=it.custom_height,
        custom_depth=it.custom_depth, custom_unit=it.custom_unit,
        order_status=order.status, created_at=order.created_at,
        buyer_name=order.full_name, buyer_phone=order.phone,
        shipping_address=order.shipping_address,
        artist_dispatched=bool(it.artist_dispatched), artist_tracking=it.artist_tracking,
        delivery_stage=(delivery.stage if delivery else None),
        delivery_tracking_id=(delivery.tracking_id if delivery else None),
        delivery_courier=(delivery.courier if delivery else None),
    )


@router.get("/me/orders", response_model=list[ArtistOrderOut])
def my_artist_orders(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Every paid sale of this artist's work, with the buyer's ship-to address and
    any custom spec, newest first."""
    slug = _my_artist_slug(me)
    items = db.scalars(
        select(OrderItem).where(OrderItem.artist_id == slug).order_by(OrderItem.created_at.desc())
    ).all()
    out = []
    for it in items:
        order = db.get(Order, it.order_id)
        if not order or order.status == "pending":
            continue  # unpaid carts aren't sales yet
        delivery = db.scalar(select(Delivery).where(Delivery.order_id == order.id))
        out.append(_artist_order_out(db, it, order, delivery))
    return out


@router.post("/me/orders/{order_item_id}/dispatch", response_model=ArtistOrderOut)
def dispatch_order_item(order_item_id: uuid.UUID, body: DispatchIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Artist ships their own piece directly to the buyer. Books a Shiprocket
    shipment from the artist's pickup address (when configured) and advances the
    order's delivery to 'dispatched' once all shippable items are out."""
    slug = _my_artist_slug(me)
    it = db.get(OrderItem, order_item_id)
    if not it or it.artist_id != slug:
        raise HTTPException(status_code=404, detail="Order item not found")
    order = db.get(Order, it.order_id)
    if not order or order.status == "pending":
        raise HTTPException(status_code=400, detail="Order is not paid yet")
    if it.fulfillment == "self_pickup":
        raise HTTPException(status_code=400, detail="This piece is self-pickup — no shipment needed")

    pickup = (me.profile.pickup_address if me.profile else None) or {}
    if not all(pickup.get(k) for k in ("line1", "city", "zip", "phone")):
        raise HTTPException(status_code=400, detail="Set your pickup address before dispatching")

    if not it.artist_dispatched:
        # Register the artist's pickup with Shiprocket once, then book the shipment.
        nickname = pickup.get("sr_nickname")
        if shipping.is_live() and not nickname:
            nickname = shipping.register_pickup(pickup, nickname=f"artist-{me.id.hex[:8]}")
            if nickname:
                me.profile.pickup_address = {**pickup, "sr_nickname": nickname}
        ship = shipping.create_item_shipment(order, it, pickup_location=nickname or settings.SHIPROCKET_PICKUP_LOCATION)
        tracking = ship or {
            "awb": (body.tracking_id or f"ART-{it.id.hex[:8].upper()}"),
            "courier": (body.courier or "Self-shipped"),
            "tracking_url": None,
        }
        it.artist_dispatched = True
        it.artist_tracking = tracking

        # Advance the order's shared delivery once every shippable item is out.
        siblings = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        shippable = [s for s in siblings if s.fulfillment != "self_pickup"]
        if shippable and all(s.artist_dispatched for s in shippable):
            delivery = db.scalar(select(Delivery).where(Delivery.order_id == order.id))
            if delivery and delivery.stage in ("order_confirmed", "curation_crating"):
                delivery.stage = "dispatched"
                if tracking.get("awb"):
                    delivery.tracking_id = tracking["awb"]
                if tracking.get("courier"):
                    delivery.courier = tracking["courier"]
                db.add(DeliveryEvent(
                    delivery_id=delivery.id, stage="dispatched",
                    title="Dispatched", detail=f"Shipped by the artist · {tracking.get('courier') or 'courier'}.",
                ))
            order.status = "shipped"
        db.commit()
        db.refresh(it)

    delivery = db.scalar(select(Delivery).where(Delivery.order_id == order.id))
    return _artist_order_out(db, it, order, delivery)


@router.get("", response_model=list[ArtistOut])
def list_artists(db: Session = Depends(get_db)):
    return list(db.scalars(select(Artist).order_by(Artist.name)).all())


@router.get("/{artist_id}", response_model=ArtistOut)
def get_artist(artist_id: str, db: Session = Depends(get_db)):
    artist = db.get(Artist, artist_id)
    if not artist:
        raise HTTPException(status_code=404, detail="Artist not found")
    return artist


@router.get("/{artist_id}/artworks", response_model=list[ArtworkOut])
def artist_artworks(artist_id: str, db: Session = Depends(get_db)):
    # Public profile shows the artist's live collection works only — not pending
    # submissions and not exhibition-only pieces.
    return list(
        db.scalars(
            select(Artwork).where(
                Artwork.artist_id == artist_id,
                Artwork.status == "active",
                Artwork.exhibition_id.is_(None),
            ).order_by(Artwork.created_at)
        ).all()
    )
