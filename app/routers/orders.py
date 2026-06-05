"""Orders: create from cart, dummy payment, admin status."""
import random
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.catalog import Artwork
from ..models.enquiry import BuyApproval
from ..models.commerce import Cart, CartItem, Order, OrderItem, Delivery, DeliveryEvent
from ..models.review import OwnedArtwork
from ..schemas.commerce import OrderCreateIn, OrderOut
from ..utils import pricing

router = APIRouter(prefix="/orders", tags=["orders"])


def _tracking_id() -> str:
    return (
        "AUR-" + str(random.randint(1000, 9999)) + "-"
        + "".join(random.choice(string.ascii_uppercase) for _ in range(2))
        + "X-0" + str(random.randint(1, 8))
    )


def _order_out(db: Session, order: Order) -> Order:
    order.items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    return order


@router.post("", response_model=OrderOut, status_code=201)
def create_order(body: OrderCreateIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    cart = db.scalar(select(Cart).where(Cart.user_id == me.id))
    items = db.scalars(select(CartItem).where(CartItem.cart_id == cart.id)).all() if cart else []
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    subtotal = sum(float(i.artwork_price) for i in items)
    transport = sum(float(i.transport_cost) for i in items)
    setup = sum(float(i.setup_cost) for i in items)
    tax = pricing.gst(subtotal)
    # Zone delivery fee only applies when something is actually shipped.
    needs_transport = any(i.fulfillment != "self_pickup" for i in items)
    has_pickup = any(i.fulfillment == "self_pickup" for i in items)

    addr = dict(body.shipping_address or {})
    # A shipped order needs a real destination address; pure self-pickup does not.
    if needs_transport and not all(addr.get(k) for k in ("line1", "city", "zip")):
        raise HTTPException(status_code=400, detail="A delivery address (line 1, city and PIN) is required for shipped items")
    # Stash pickup scheduling on the order's JSON (no dedicated column needed).
    if has_pickup:
        addr["pickup_date"] = body.pickup_date
        addr["pickup_slot"] = body.pickup_slot

    pincode = body.pincode or addr.get("zip")
    delivery_fee = pricing.delivery_estimate(pincode)["delivery_fee"] if needs_transport else 0.0
    total = subtotal + transport + setup + tax + delivery_fee

    order = Order(
        user_id=me.id, email=me.email, full_name=body.full_name, phone=body.phone,
        shipping_address=addr, subtotal=subtotal, tax=tax,
        delivery_fee=delivery_fee, total=total,
        status="pending", payment_provider=body.payment_provider, breakdown=[],
    )
    db.add(order)
    db.flush()  # get order.id

    breakdown = []
    for it in items:
        art = db.get(Artwork, it.artwork_id)
        db.add(OrderItem(
            order_id=order.id, artwork_id=it.artwork_id,
            title=art.title if art else None, price=it.artwork_price, qty=it.qty,
            fulfillment=it.fulfillment, transport_cost=it.transport_cost, setup_cost=it.setup_cost,
        ))
        breakdown.append({
            "artwork_id": it.artwork_id, "title": art.title if art else None,
            "artwork_price": float(it.artwork_price), "transport_cost": float(it.transport_cost),
            "setup_cost": float(it.setup_cost), "fulfillment": it.fulfillment,
        })
        # consume the approval + clear cart line
        if it.approval_id:
            appr = db.get(BuyApproval, it.approval_id)
            if appr:
                appr.consumed = True
        db.delete(it)
    order.breakdown = breakdown
    db.commit()
    db.refresh(order)
    return _order_out(db, order)


@router.post("/{order_id}/pay", response_model=OrderOut)
def pay(order_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Dummy payment — marks the order paid, opens a delivery, grants digital ownership."""
    order = db.get(Order, order_id)
    if not order or order.user_id != me.id:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "pending":
        return _order_out(db, order)

    order.status = "paid"
    order.payment_id = "dummy_" + uuid.uuid4().hex[:12]
    order.payment_meta = {"provider": order.payment_provider, "dummy": True}

    est = pricing.delivery_estimate((order.shipping_address or {}).get("zip"))
    delivery = Delivery(
        order_id=order.id, tracking_id=_tracking_id(), stage="order_confirmed",
        courier="Blue Dart", eta=est["eta"], current_location=pricing.VAULT["name"],
    )
    db.add(delivery)
    db.flush()
    db.add(DeliveryEvent(
        delivery_id=delivery.id, stage="order_confirmed",
        title="Order Confirmed", detail="Payment received. Curator assigned.",
    ))

    # digital ownership granted immediately on payment
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    for it in items:
        art = db.get(Artwork, it.artwork_id) if it.artwork_id else None
        db.add(OwnedArtwork(
            user_id=me.id, artwork_id=it.artwork_id, order_id=order.id, kind="digital",
            digital_asset_url=(art.images[0] if art and art.images else None),
        ))
    db.commit()
    db.refresh(order)
    return _order_out(db, order)


@router.get("/mine", response_model=list[OrderOut])
def my_orders(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    orders = db.scalars(select(Order).where(Order.user_id == me.id).order_by(Order.created_at.desc())).all()
    return [_order_out(db, o) for o in orders]


@router.get("", response_model=list[OrderOut])
def all_orders(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    orders = db.scalars(select(Order).order_by(Order.created_at.desc())).all()
    return [_order_out(db, o) for o in orders]


@router.patch("/{order_id}/status", response_model=OrderOut)
def set_status(order_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    status = body.get("status")
    if status not in {"pending", "paid", "shipped", "delivered", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    order.status = status
    db.commit()
    db.refresh(order)
    return _order_out(db, order)
