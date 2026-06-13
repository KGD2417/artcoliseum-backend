"""Online exhibitions: admin runs a registration window, approved artists submit
approved artworks, then the curated show goes live as an online gallery."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user, require_role
from ..models.user import User
from ..models.catalog import Artwork
from ..models.exhibition import Exhibition, ExhibitionSubmission
from ..schemas.exhibition import ExhibitionIn, ExhibitionUpdate, ExhibitionOut, SubmitIn

router = APIRouter(prefix="/exhibitions", tags=["exhibitions"])


def _artist_slug(user: User) -> str:
    return f"artist-{user.id.hex[:8]}"


def _is_admin(me: User | None) -> bool:
    return bool(me and me.profile and me.profile.role == "admin")


def _is_approved_artist(me: User | None) -> bool:
    return bool(me and me.profile and me.profile.artist_status == "verified")


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
        select(func.count()).select_from(ExhibitionSubmission)
        .where(ExhibitionSubmission.exhibition_id == ex_id)
    ) or 0


def _live_artworks(db: Session, ex_id: uuid.UUID) -> list[Artwork]:
    """Approved artworks submitted to this exhibition, in submission order."""
    rows = db.scalars(
        select(ExhibitionSubmission)
        .where(ExhibitionSubmission.exhibition_id == ex_id)
        .order_by(ExhibitionSubmission.created_at)
    ).all()
    out = []
    for s in rows:
        art = db.get(Artwork, s.artwork_id)
        if art and art.status == "active":
            out.append(art)
    return out


def _serialize(db: Session, ex: Exhibition, *, with_artworks: bool) -> ExhibitionOut:
    phase = _phase(ex)
    data = ExhibitionOut.model_validate(ex)
    data.status = phase
    data.submission_count = _submission_count(db, ex.id)
    if with_artworks and phase == "live":
        from ..schemas.catalog import ArtworkOut
        data.artworks = [ArtworkOut.model_validate(a) for a in _live_artworks(db, ex.id)]
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


@router.get("/current/mine", response_model=list[str])
def my_submissions(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Artwork ids the caller has submitted to the current exhibition."""
    ex = _active_exhibition(db)
    if not ex:
        return []
    return list(db.scalars(
        select(ExhibitionSubmission.artwork_id)
        .where(ExhibitionSubmission.exhibition_id == ex.id,
               ExhibitionSubmission.user_id == me.id)
    ).all())


@router.post("/current/submit", response_model=list[str])
def submit_to_current(body: SubmitIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Approved artist submits their approved artworks to the open exhibition."""
    if not (_is_approved_artist(me) or _is_admin(me)):
        raise HTTPException(status_code=403, detail="Only approved artists may submit")
    ex = _active_exhibition(db)
    if not ex or _phase(ex) != "registration":
        raise HTTPException(status_code=400, detail="Registration is not open right now")

    slug = _artist_slug(me)
    existing = set(db.scalars(
        select(ExhibitionSubmission.artwork_id)
        .where(ExhibitionSubmission.exhibition_id == ex.id,
               ExhibitionSubmission.user_id == me.id)
    ).all())
    for aid in body.artwork_ids:
        art = db.get(Artwork, aid)
        if not art:
            continue
        # Must be the caller's own, approved artwork (admins may submit any active work).
        if not _is_admin(me) and art.artist_id != slug:
            continue
        if art.status != "active":
            raise HTTPException(status_code=400, detail=f"'{art.title}' must be approved before it can be exhibited")
        if aid in existing:
            continue
        db.add(ExhibitionSubmission(
            exhibition_id=ex.id, user_id=me.id, artist_id=art.artist_id, artwork_id=aid,
        ))
        existing.add(aid)
    db.commit()
    return list(existing)


@router.delete("/current/submit/{artwork_id}", status_code=204)
def withdraw_from_current(artwork_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    ex = _active_exhibition(db)
    if not ex or _phase(ex) != "registration":
        raise HTTPException(status_code=400, detail="Registration is closed — submissions are locked")
    sub = db.scalar(
        select(ExhibitionSubmission).where(
            ExhibitionSubmission.exhibition_id == ex.id,
            ExhibitionSubmission.user_id == me.id,
            ExhibitionSubmission.artwork_id == artwork_id,
        )
    )
    if sub:
        db.delete(sub)
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
    rows = db.scalars(
        select(ExhibitionSubmission).where(ExhibitionSubmission.exhibition_id == exhibition_id)
        .order_by(ExhibitionSubmission.created_at)
    ).all()
    out = []
    for s in rows:
        art = db.get(Artwork, s.artwork_id)
        out.append({
            "id": str(s.id), "artwork_id": s.artwork_id,
            "title": art.title if art else s.artwork_id,
            "artist_name": art.artist_name if art else None,
            "image": (art.images[0] if art and art.images else None),
            "status": art.status if art else "missing",
        })
    return out
