"""Server-side cart. Items can only be added if the user holds an active
buy-approval for that artwork (the enquiry gate is enforced here too)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artwork, ArtworkSize
from ..models.enquiry import BuyApproval
from ..models.commerce import Cart, CartItem
from ..schemas.commerce import CartItemIn, CartItemPatch, CartBreakdownOut, CartItemDetail
from ..utils import pricing

router = APIRouter(prefix="/cart", tags=["cart"])


def _get_or_create_cart(db: Session, user: User) -> Cart:
    cart = db.scalar(select(Cart).where(Cart.user_id == user.id))
    if not cart:
        cart = Cart(user_id=user.id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def _breakdown(db: Session, cart: Cart) -> CartBreakdownOut:
    items = db.scalars(select(CartItem).where(CartItem.cart_id == cart.id).order_by(CartItem.created_at)).all()
    details, art_sub, t_sub, s_sub = [], 0.0, 0.0, 0.0
    for it in items:
        art = db.get(Artwork, it.artwork_id)
        ap = float(it.artwork_price)
        t = float(it.transport_cost)
        s = float(it.setup_cost)
        art_sub += ap; t_sub += t; s_sub += s
        details.append(CartItemDetail(
            id=it.id, artwork_id=it.artwork_id, artwork_price=ap, fulfillment=it.fulfillment,
            transport_cost=t, setup_cost=s, qty=it.qty,
            title=art.title if art else None,
            image=(art.images[0] if art and art.images else None),
            artist_name=art.artist_name if art else None,
            line_total=ap + t + s,
        ))
    gst = pricing.gst(art_sub)
    return CartBreakdownOut(
        items=details, artwork_subtotal=art_sub, transport_subtotal=t_sub,
        setup_subtotal=s_sub, gst=gst, total=art_sub + t_sub + s_sub + gst,
    )


@router.get("/breakdown", response_model=CartBreakdownOut)
def breakdown(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _breakdown(db, _get_or_create_cart(db, me))


@router.post("/items", response_model=CartBreakdownOut, status_code=201)
def add_item(body: CartItemIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if body.fulfillment not in pricing.FULFILLMENTS:
        raise HTTPException(status_code=400, detail="Invalid fulfillment")

    appr = db.scalar(
        select(BuyApproval).where(
            BuyApproval.user_id == me.id,
            BuyApproval.artwork_id == body.artwork_id,
            BuyApproval.consumed == False,  # noqa: E712
        )
    )
    if appr:
        price = float(appr.final_price)
        approval_id = appr.id
    else:
        # No approval — only allowed for predefined (non-customizable) artworks,
        # which carry a fixed price (optionally per selected size).
        art = db.get(Artwork, body.artwork_id)
        if not art:
            raise HTTPException(status_code=404, detail="Artwork not found")
        if art.customizable:
            raise HTTPException(status_code=403, detail="Not approved to buy this artwork yet")
        price = float(art.price or 0)
        if body.size_id:
            sz = db.get(ArtworkSize, body.size_id)
            if sz and str(sz.artwork_id) == str(art.id):
                price = float(sz.price)
        approval_id = None

    cart = _get_or_create_cart(db, me)
    existing = db.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.artwork_id == body.artwork_id)
    )
    costs = pricing.line_costs(price, body.fulfillment)
    if existing:
        existing.fulfillment = body.fulfillment
        existing.transport_cost = costs["transport_cost"]
        existing.setup_cost = costs["setup_cost"]
    else:
        db.add(CartItem(
            cart_id=cart.id, artwork_id=body.artwork_id, approval_id=approval_id,
            artwork_price=price, size_id=body.size_id, fulfillment=body.fulfillment,
            transport_cost=costs["transport_cost"], setup_cost=costs["setup_cost"], qty=1,
        ))
    db.commit()
    return _breakdown(db, cart)


@router.patch("/items/{item_id}", response_model=CartBreakdownOut)
def update_item(item_id: uuid.UUID, body: CartItemPatch, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if body.fulfillment not in pricing.FULFILLMENTS:
        raise HTTPException(status_code=400, detail="Invalid fulfillment")
    cart = _get_or_create_cart(db, me)
    it = db.get(CartItem, item_id)
    if not it or it.cart_id != cart.id:
        raise HTTPException(status_code=404, detail="Item not found")
    costs = pricing.line_costs(float(it.artwork_price), body.fulfillment)
    it.fulfillment = body.fulfillment
    it.transport_cost = costs["transport_cost"]
    it.setup_cost = costs["setup_cost"]
    db.commit()
    return _breakdown(db, cart)


@router.delete("/items/{item_id}", response_model=CartBreakdownOut)
def remove_item(item_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    cart = _get_or_create_cart(db, me)
    it = db.get(CartItem, item_id)
    if it and it.cart_id == cart.id:
        db.delete(it)
        db.commit()
    return _breakdown(db, cart)
