"""Wishlist / Save-for-later: a buyer's saved artworks. Anyone signed in can save
any artwork to revisit or buy later — no buy-approval needed (that gate only
applies when adding to the cart)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artwork
from ..models.community import CommunityPost, Bid
from ..models.wishlist import WishlistItem, SavedPost
from ..schemas.commerce import (
    WishlistAddIn, WishlistItemOut, SavedPostAddIn, SavedListingOut,
)

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


# ── Saved community marketplace listings (shares the "Saved for Later" UI) ─────

def _listing_price(db: Session, p: CommunityPost) -> float | None:
    """Display price for a saved listing: the current top bid, else the
    starting bid for auctions; plain listings carry no price."""
    if not p.is_auction:
        return None
    top = db.scalar(select(func.max(Bid.amount)).where(Bid.post_id == p.id))
    if top is not None:
        return float(top)
    return float(p.starting_bid) if p.starting_bid is not None else None


def _saved_post_ids(db: Session, me: User) -> list[str]:
    return [str(pid) for pid in db.scalars(
        select(SavedPost.post_id).where(SavedPost.user_id == me.id)
    ).all()]


@router.get("/posts", response_model=list[SavedListingOut])
def my_saved_posts(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The buyer's saved marketplace listings, newest first, with display details."""
    rows = db.scalars(
        select(SavedPost)
        .where(SavedPost.user_id == me.id)
        .order_by(SavedPost.created_at.desc())
    ).all()
    out = []
    for s in rows:
        p = db.get(CommunityPost, s.post_id)
        out.append(SavedListingOut(
            post_id=str(s.post_id),
            title=(p.title if p else None),
            image=(p.images[0] if p and p.images else None),
            is_auction=bool(p.is_auction) if p else False,
            price=_listing_price(db, p) if p else None,
            available=bool(p and not p.auction_closed),
            created_at=s.created_at,
        ))
    return out


@router.get("/posts/ids", response_model=list[str])
def my_saved_post_ids(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Just the saved listing ids — for cheap membership checks in the feed."""
    return _saved_post_ids(db, me)


@router.post("/posts", response_model=list[str])
def add_saved_post(body: SavedPostAddIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Save a listing. Idempotent. Returns the updated list of saved listing ids."""
    p = db.get(CommunityPost, body.post_id)
    if p:  # ignore unknown ids rather than erroring the save toggle
        exists = db.scalar(
            select(SavedPost).where(
                SavedPost.user_id == me.id, SavedPost.post_id == p.id
            )
        )
        if not exists:
            db.add(SavedPost(user_id=me.id, post_id=p.id))
            db.commit()
    return _saved_post_ids(db, me)


@router.delete("/posts/{post_id}", response_model=list[str])
def remove_saved_post(post_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Unsave a listing. Returns the updated saved listing-id list."""
    db.execute(
        delete(SavedPost).where(
            SavedPost.user_id == me.id, SavedPost.post_id == post_id
        )
    )
    db.commit()
    return _saved_post_ids(db, me)
