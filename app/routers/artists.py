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
    """Submit artist KYC → become a PENDING artist, awaiting admin approval."""
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
    if kyc:
        kyc.name = body.name; kyc.age = body.age; kyc.art_type = body.art_type
        kyc.location = body.location; kyc.about = body.about; kyc.avatar_url = body.avatar_url
        kyc.gender = body.gender
        if kyc.status not in ("verified",):
            kyc.status = "pending"
    else:
        db.add(ArtistKyc(
            user_id=me.id, name=body.name, age=body.age, art_type=body.art_type,
            location=body.location, about=body.about, avatar_url=body.avatar_url,
            gender=body.gender, status="pending",
        ))
    # none → pending (awaiting approval). Never downgrade an already-verified artist.
    if me.profile and me.profile.artist_status in ("none", "unverified"):
        me.profile.artist_status = "pending"
    db.commit()
    return ArtistStatusOut(
        artist_status=me.profile.artist_status if me.profile else "pending",
        role=me.profile.role if me.profile else "user",
    )


@router.get("/me/status", response_model=ArtistStatusOut)
def my_status(me: User = Depends(get_current_user)):
    return ArtistStatusOut(
        artist_status=me.profile.artist_status if me.profile else "none",
        role=me.profile.role if me.profile else "user",
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
