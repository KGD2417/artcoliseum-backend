"""Online exhibitions: admin runs a registration window, approved artists submit
*dedicated* exhibition artworks (separate from the collection, sold within the
show), then the curated show goes live as an online gallery."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user, require_role
from ..models.user import User
from ..models.catalog import Artwork, Artist, Category
from ..models.competition import ArtistKyc
from ..schemas.catalog import ArtworkOut
from ..schemas.exhibition import ExhibitionIn, ExhibitionUpdate, ExhibitionOut, ExhibitionArtworkIn

router = APIRouter(prefix="/exhibitions", tags=["exhibitions"])


def _artist_slug(user: User) -> str:
    return f"artist-{user.id.hex[:8]}"


def _is_admin(me: User | None) -> bool:
    return bool(me and me.profile and me.profile.role == "admin")


def _is_approved_artist(me: User | None) -> bool:
    return bool(me and me.profile and me.profile.artist_status == "verified")


def _fmt_num(n) -> str:
    f = float(n)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _compose_dims(width, height, depth, unit) -> str | None:
    parts = [p for p in (width, height, depth) if p is not None]
    if len(parts) < 2:
        return None
    return f"{' × '.join(_fmt_num(p) for p in parts)} {unit or 'cm'}"


def _ensure_artist(db: Session, me: User) -> tuple[str, str]:
    """Resolve (and lazily seed from KYC) the caller's catalog Artist row."""
    slug = _artist_slug(me)
    name = (me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0])
    if not db.get(Artist, slug):
        kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == me.id))
        db.add(Artist(
            id=slug, name=name, role="Art Coliseum Artist",
            bio=(kyc.about if kyc else None),
            image_url=(kyc.avatar_url if kyc else (me.profile.avatar_url if me.profile else None)),
            location=(kyc.location if kyc else None), age=(kyc.age if kyc else None),
            art_type=(kyc.art_type if kyc else None), gender=(kyc.gender if kyc else None),
        ))
    return slug, name


def _phase(ex: Exhibition) -> str:
    """Effective phase. Admin status is authoritative, but a registration window
    auto-advances by its dates: upcoming → registration → live."""
    if ex.status in ("draft", "ended", "live"):
        return ex.status
    # ex.status == "registration": refine by the window dates.
    now = datetime.now(timezone.utc)
    starts, ends = ex.registration_starts_at, ex.registration_ends_at
    if starts and now < starts:
        return "upcoming"
    if ends and now > ends:
        return "live"
    return "registration"


def _submission_count(db: Session, ex_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Artwork).where(Artwork.exhibition_id == ex_id)
    ) or 0


def _exhibition_artworks(db: Session, ex_id: uuid.UUID, *, active_only: bool) -> list[Artwork]:
    """The exhibition's own artworks, in submission order."""
    stmt = select(Artwork).where(Artwork.exhibition_id == ex_id)
    if active_only:
        stmt = stmt.where(Artwork.status == "active")
    return list(db.scalars(stmt.order_by(Artwork.created_at)).all())


def _serialize(db: Session, ex: Exhibition, *, with_artworks: bool) -> ExhibitionOut:
    phase = _phase(ex)
    data = ExhibitionOut.model_validate(ex)
    data.status = phase
    data.submission_count = _submission_count(db, ex.id)
    if with_artworks and phase == "live":
        data.artworks = [ArtworkOut.model_validate(a) for a in _exhibition_artworks(db, ex.id, active_only=True)]
    return data


def _active_exhibition(db: Session) -> Exhibition | None:
    """The single non-ended exhibition, if any (most recently created)."""
    return db.scalars(
        select(Exhibition).where(Exhibition.status != "ended")
        .order_by(Exhibition.created_at.desc())
    ).first()


# ── Public ───────────────────────────────────────────────────────────────────
@router.get("/current", response_model=ExhibitionOut | None)
def current_exhibition(db: Session = Depends(get_db), me: User | None = Depends(get_optional_user)):
    ex = _active_exhibition(db)
    if not ex:
        return None
    return _serialize(db, ex, with_artworks=True)


@router.get("/current/mine", response_model=list[ArtworkOut])
def my_submissions(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """The caller's own artworks submitted to the current exhibition."""
    ex = _active_exhibition(db)
    if not ex:
        return []
    slug = _artist_slug(me)
    return list(db.scalars(
        select(Artwork).where(Artwork.exhibition_id == ex.id, Artwork.artist_id == slug)
        .order_by(Artwork.created_at)
    ).all())


@router.post("/current/artworks", response_model=ArtworkOut, status_code=201)
def submit_artwork(body: ExhibitionArtworkIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Approved artist submits a NEW, exhibition-only artwork during registration.
    These never appear in the collection — only inside the show."""
    if not (_is_approved_artist(me) or _is_admin(me)):
        raise HTTPException(status_code=403, detail="Only approved artists may submit")
    ex = _active_exhibition(db)
    if not ex or _phase(ex) != "registration":
        raise HTTPException(status_code=400, detail="Registration is not open right now")
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if not body.price or float(body.price) <= 0:
        raise HTTPException(status_code=400, detail="An exhibition piece needs a price greater than 0")
    if body.category_id and not db.get(Category, body.category_id):
        raise HTTPException(status_code=400, detail="category_id does not exist")

    slug, name = _ensure_artist(db, me)
    base_dims = _compose_dims(body.width, body.height, body.depth, body.unit or "cm")
    aid = f"ex-{uuid.uuid4().hex[:10]}"
    art = Artwork(
        id=aid, title=body.title.strip(), narrative=body.narrative, description=body.narrative,
        medium=body.medium, artist_id=slug, artist_name=name,
        year=body.year or str(datetime.now().year),
        price=float(body.price), category_id=body.category_id,
        width=body.width, height=body.height, depth=body.depth, base_dimensions=base_dims,
        customizable=False, images=body.images or [],
        # Exhibition pieces are curated through the show itself → live immediately,
        # but flagged so they never surface in the public collection/store.
        status="active", in_stock=True, exhibition_id=ex.id,
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


@router.delete("/current/artworks/{artwork_id}", status_code=204)
def withdraw_artwork(artwork_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Withdraw (delete) one of the caller's exhibition pieces during registration."""
    ex = _active_exhibition(db)
    if not ex or _phase(ex) != "registration":
        raise HTTPException(status_code=400, detail="Registration is closed — submissions are locked")
    art = db.get(Artwork, artwork_id)
    if art and art.exhibition_id == ex.id and (_is_admin(me) or art.artist_id == _artist_slug(me)):
        db.delete(art)
        db.commit()
    return None


# ── Admin ────────────────────────────────────────────────────────────────────
@router.get("", response_model=list[ExhibitionOut])
def list_exhibitions(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(Exhibition).order_by(Exhibition.created_at.desc())).all()
    return [_serialize(db, ex, with_artworks=False) for ex in rows]


@router.post("", response_model=ExhibitionOut, status_code=201)
def create_exhibition(body: ExhibitionIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    if _active_exhibition(db):
        raise HTTPException(status_code=400, detail="An exhibition is already running — end it before starting another")
    ex = Exhibition(
        title=body.title, description=body.description, theme=body.theme,
        hero_image_url=body.hero_image_url, status="draft",
        registration_starts_at=body.registration_starts_at,
        registration_ends_at=body.registration_ends_at,
    )
    db.add(ex); db.commit(); db.refresh(ex)
    return _serialize(db, ex, with_artworks=False)


@router.patch("/{exhibition_id}", response_model=ExhibitionOut)
def update_exhibition(exhibition_id: uuid.UUID, body: ExhibitionUpdate, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    ex = db.get(Exhibition, exhibition_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Exhibition not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(ex, key, value)
    db.commit(); db.refresh(ex)
    return _serialize(db, ex, with_artworks=False)


def _set_status(db: Session, exhibition_id: uuid.UUID, status: str) -> Exhibition:
    ex = db.get(Exhibition, exhibition_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Exhibition not found")
    ex.status = status
    db.commit(); db.refresh(ex)
    return ex


@router.post("/{exhibition_id}/open", response_model=ExhibitionOut)
def open_registration(exhibition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _serialize(db, _set_status(db, exhibition_id, "registration"), with_artworks=False)


@router.post("/{exhibition_id}/go-live", response_model=ExhibitionOut)
def go_live(exhibition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _serialize(db, _set_status(db, exhibition_id, "live"), with_artworks=True)


@router.post("/{exhibition_id}/end", response_model=ExhibitionOut)
def end_exhibition(exhibition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _serialize(db, _set_status(db, exhibition_id, "ended"), with_artworks=False)


@router.get("/{exhibition_id}/submissions")
def list_submissions(exhibition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    arts = _exhibition_artworks(db, exhibition_id, active_only=False)
    return [{
        "id": a.id, "artwork_id": a.id, "title": a.title,
        "artist_name": a.artist_name, "price": float(a.price or 0),
        "image": (a.images[0] if a.images else None), "status": a.status,
    } for a in arts]
