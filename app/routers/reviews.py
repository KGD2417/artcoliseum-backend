"""Reviews/testimonials + owned artworks (digital + physical)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artwork
from ..models.review import Review, OwnedArtwork
from ..schemas.commerce import ReviewIn, ReviewOut, OwnedOut

router = APIRouter(tags=["reviews"])


@router.post("/reviews", response_model=ReviewOut, status_code=201)
def create_review(body: ReviewIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    author = me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0]
    review = Review(
        user_id=me.id, artwork_id=body.artwork_id, order_id=body.order_id,
        rating=max(1, min(5, body.rating)), text=body.text, images=body.images or [],
        author_name=author, published=True,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("/reviews", response_model=list[ReviewOut])
def list_reviews(db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Review).where(Review.published == True).order_by(Review.created_at.desc())  # noqa: E712
    ).all())


@router.get("/reviews/artwork/{artwork_id}", response_model=list[ReviewOut])
def artwork_reviews(artwork_id: str, db: Session = Depends(get_db)):
    return list(db.scalars(
        select(Review).where(Review.artwork_id == artwork_id, Review.published == True)  # noqa: E712
        .order_by(Review.created_at.desc())
    ).all())


@router.get("/owned", response_model=list[OwnedOut])
def my_owned(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    rows = db.scalars(
        select(OwnedArtwork).where(OwnedArtwork.user_id == me.id).order_by(OwnedArtwork.acquired_at.desc())
    ).all()
    out = []
    for r in rows:
        art = db.get(Artwork, r.artwork_id)
        out.append(OwnedOut(
            id=r.id, artwork_id=r.artwork_id, kind=r.kind,
            digital_asset_url=r.digital_asset_url, acquired_at=r.acquired_at,
            title=art.title if art else None,
            image=(art.images[0] if art and art.images else r.digital_asset_url),
            artist_name=art.artist_name if art else None,
        ))
    return out
