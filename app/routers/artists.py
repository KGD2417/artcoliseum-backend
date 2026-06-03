"""Public artist listing + profile, plus artist KYC onboarding."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User
from ..models.catalog import Artist, Artwork
from ..models.competition import ArtistKyc
from ..schemas.catalog import ArtistOut, ArtworkOut
from ..schemas.extra import KycIn, ArtistStatusOut

router = APIRouter(prefix="/artists", tags=["artists"])


@router.post("/apply", response_model=ArtistStatusOut)
def apply_artist(body: KycIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Submit artist KYC → become an UNVERIFIED artist (eligible for the competition)."""
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
    if kyc:
        kyc.name = body.name; kyc.age = body.age; kyc.art_type = body.art_type
        kyc.location = body.location; kyc.about = body.about; kyc.avatar_url = body.avatar_url
    else:
        db.add(ArtistKyc(
            user_id=me.id, name=body.name, age=body.age, art_type=body.art_type,
            location=body.location, about=body.about, avatar_url=body.avatar_url, status="unverified",
        ))
    if me.profile and me.profile.artist_status == "none":
        me.profile.artist_status = "unverified"
    db.commit()
    return ArtistStatusOut(
        artist_status=me.profile.artist_status if me.profile else "unverified",
        role=me.profile.role if me.profile else "user",
    )


@router.get("/me/status", response_model=ArtistStatusOut)
def my_status(me: User = Depends(get_current_user)):
    return ArtistStatusOut(
        artist_status=me.profile.artist_status if me.profile else "none",
        role=me.profile.role if me.profile else "user",
    )


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
    return list(
        db.scalars(
            select(Artwork).where(Artwork.artist_id == artist_id).order_by(Artwork.created_at)
        ).all()
    )
