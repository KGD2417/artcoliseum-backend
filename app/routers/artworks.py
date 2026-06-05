"""Public artwork browsing + verified-artist / admin authoring."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.catalog import Artwork, Artist, Category, ArtworkSize
from ..schemas.catalog import ArtworkOut
from ..schemas.extra import ArtworkCreateIn

router = APIRouter(prefix="/artworks", tags=["artworks"])


def _slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def _artist_slug(user: User) -> str:
    """The catalog Artist id a logged-in artist authors under."""
    return f"artist-{user.id.hex[:8]}"


def _can_manage(me: User, art: Artwork) -> bool:
    is_admin = bool(me.profile and me.profile.role == "admin")
    return is_admin or art.artist_id == _artist_slug(me)


@router.get("", response_model=list[ArtworkOut])
def list_artworks(
    category: str | None = Query(None),
    subtype: str | None = Query(None),
    style: str | None = Query(None),
    size: str | None = Query(None),
    artist_id: str | None = Query(None),
    featured: bool | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Artwork)
    if category:
        stmt = stmt.where(Artwork.category_id == category)
    if subtype:
        stmt = stmt.where(Artwork.subtype_id == subtype)
    if style:
        stmt = stmt.where(Artwork.style == style)
    if size:
        stmt = stmt.where(Artwork.size == size)
    if artist_id:
        stmt = stmt.where(Artwork.artist_id == artist_id)
    if featured is not None:
        stmt = stmt.where(Artwork.featured == featured)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (Artwork.title.ilike(like)) | (Artwork.artist_name.ilike(like))
        )
    stmt = stmt.order_by(Artwork.created_at)
    return list(db.scalars(stmt).all())


@router.get("/mine", response_model=list[ArtworkOut])
def my_artworks(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The logged-in artist's own works (for the artist dashboard)."""
    slug = _artist_slug(me)
    return list(db.scalars(
        select(Artwork).where(Artwork.artist_id == slug).order_by(Artwork.created_at.desc())
    ).all())


@router.get("/{artwork_id}", response_model=ArtworkOut)
def get_artwork(artwork_id: str, db: Session = Depends(get_db)):
    art = db.get(Artwork, artwork_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return art


@router.post("", response_model=ArtworkOut, status_code=201)
def create_artwork(body: ArtworkCreateIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    role = me.profile.role if me.profile else "user"
    verified = me.profile and me.profile.artist_status == "verified"
    if role != "admin" and not verified:
        raise HTTPException(status_code=403, detail="Only verified artists may submit artworks")

    # main medium must already exist; subtype optional but must exist if given
    main = db.get(Category, body.category_id)
    if not main or main.kind != "main":
        raise HTTPException(status_code=400, detail="category_id must be an existing main medium")
    if body.subtype_id and not db.get(Category, body.subtype_id):
        raise HTTPException(status_code=400, detail="subtype_id does not exist")

    # Resolve the catalog Artist row. Admins may attach the work to any artist
    # (e.g. one they added directly); verified artists author under themselves.
    if role == "admin" and body.artist_id:
        artist_slug = body.artist_id
        artist = db.get(Artist, artist_slug)
        name = artist.name if artist else (me.profile.full_name if me.profile and me.profile.full_name else "Art Coliseum Artist")
        if not artist:
            db.add(Artist(id=artist_slug, name=name, role="Art Coliseum Artist"))
    else:
        artist_slug = f"artist-{me.id.hex[:8]}"
        artist = db.get(Artist, artist_slug)
        name = (me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0])
        if not artist:
            db.add(Artist(id=artist_slug, name=name, role="Art Coliseum Artist"))

    # Predefined (non-customizable) works must carry a concrete price so buyers
    # can purchase directly. Fall back to the cheapest predefined size if needed.
    price = float(body.price or 0)
    if not body.customizable and price <= 0 and body.predefined_sizes:
        sized = [float(s.get("price", 0) or 0) for s in body.predefined_sizes if s.get("price")]
        if sized:
            price = min(sized)
    if not body.customizable and price <= 0:
        raise HTTPException(status_code=400, detail="Predefined artworks need a price greater than 0")

    aid = f"aw-{uuid.uuid4().hex[:10]}"
    art = Artwork(
        id=aid, title=body.title, narrative=body.narrative, description=body.narrative,
        medium=body.medium, artist_id=artist_slug, artist_name=name,
        year=body.year or str(__import__("datetime").datetime.now().year),
        price=price, category_id=body.category_id, subtype_id=body.subtype_id,
        base_dimensions=body.base_dimensions, customizable=body.customizable,
        price_per_unit=body.price_per_unit, unit=body.unit,
        min_width=body.min_width, max_width=body.max_width,
        min_height=body.min_height, max_height=body.max_height,
        min_depth=body.min_depth, max_depth=body.max_depth, featured=body.featured,
        frame_options=body.frame_options, finish_options=body.finish_options,
        palette_options=body.palette_options,
        images=body.images or [], videos=body.videos or [], model_3d_url=body.model_3d_url,
        status="active", in_stock=True,
    )
    db.add(art)
    db.flush()
    for sz in (body.predefined_sizes or []):
        db.add(ArtworkSize(
            artwork_id=aid, label=sz.get("label", "Size"),
            width=sz.get("width"), height=sz.get("height"), depth=sz.get("depth"),
            unit=sz.get("unit"), price=sz.get("price", 0),
        ))
    db.commit()
    db.refresh(art)
    return art


# Fields an owning artist may edit; admins may additionally edit the rest.
_ARTIST_EDITABLE = {
    "title", "price", "medium", "in_stock", "category_id", "style", "subtype_id",
    "base_dimensions", "customizable", "price_per_unit", "unit",
    "min_width", "max_width", "min_height", "max_height", "min_depth", "max_depth",
    "frame_options", "finish_options", "palette_options",
}
_ADMIN_ONLY = {"status", "featured"}


@router.patch("/{artwork_id}", response_model=ArtworkOut)
def update_artwork(artwork_id: str, body: dict, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    art = db.get(Artwork, artwork_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artwork not found")
    if not _can_manage(me, art):
        raise HTTPException(status_code=403, detail="Not allowed to edit this artwork")
    is_admin = bool(me.profile and me.profile.role == "admin")
    allowed = _ARTIST_EDITABLE | _ADMIN_ONLY if is_admin else _ARTIST_EDITABLE
    for field in allowed:
        if field in body and body[field] is not None:
            setattr(art, field, body[field])
    db.commit()
    db.refresh(art)
    return art


@router.delete("/{artwork_id}", status_code=204)
def delete_artwork(artwork_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    art = db.get(Artwork, artwork_id)
    if art:
        if not _can_manage(me, art):
            raise HTTPException(status_code=403, detail="Not allowed to delete this artwork")
        db.delete(art)
        db.commit()
    return None
