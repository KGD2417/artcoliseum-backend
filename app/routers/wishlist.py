"""Wishlist / Save-for-later: a buyer's saved artworks. Anyone signed in can save
any artwork to revisit or buy later — no buy-approval needed (that gate only
applies when adding to the cart)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artwork
from ..models.wishlist import WishlistItem
from ..schemas.commerce import WishlistAddIn, WishlistItemOut

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


@router.get("", response_model=list[WishlistItemOut])
def my_wishlist(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The buyer's saved artworks, newest first, with display details."""
    rows = db.scalars(
        select(WishlistItem)
        .where(WishlistItem.user_id == me.id)
        .order_by(WishlistItem.created_at.desc())
    ).all()
    out = []
    for w in rows:
        art = db.get(Artwork, w.artwork_id)
        out.append(WishlistItemOut(
            artwork_id=w.artwork_id,
            title=art.title if art else None,
            image=(art.images[0] if art and art.images else None),
            artist_name=art.artist_name if art else None,
            price=float(art.price) if art and art.price is not None else None,
            customizable=bool(art.customizable) if art else False,
            available=bool(art and art.status == "active"),
            created_at=w.created_at,
        ))
    return out


@router.get("/ids", response_model=list[str])
def my_wishlist_ids(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Just the saved artwork ids — for cheap membership checks on product pages."""
    return list(db.scalars(
        select(WishlistItem.artwork_id).where(WishlistItem.user_id == me.id)
    ).all())


@router.post("", response_model=list[str])
def add_to_wishlist(body: WishlistAddIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Save an artwork. Idempotent — saving an already-saved piece is a no-op.
    Returns the updated list of saved artwork ids."""
    art = db.get(Artwork, body.artwork_id)
    if art:  # silently ignore unknown ids rather than erroring the heart toggle
        exists = db.scalar(
            select(WishlistItem).where(
                WishlistItem.user_id == me.id, WishlistItem.artwork_id == body.artwork_id
            )
        )
        if not exists:
            db.add(WishlistItem(user_id=me.id, artwork_id=body.artwork_id))
            db.commit()
    return my_wishlist_ids(db, me)


@router.delete("/{artwork_id}", response_model=list[str])
def remove_from_wishlist(artwork_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Remove an artwork from the wishlist. Returns the updated saved-id list."""
    db.execute(
        delete(WishlistItem).where(
            WishlistItem.user_id == me.id, WishlistItem.artwork_id == artwork_id
        )
    )
    db.commit()
    return my_wishlist_ids(db, me)
