"""Monthly competition: unverified artists enter; an external jury rates entries on
the day; the highest-rated entry wins and its artist becomes VERIFIED."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user, require_role
from ..models.user import User, Profile
from ..models.competition import Competition, CompetitionEntry, JuryVerdict, ArtistKyc
from ..schemas.extra import CompetitionIn, CompetitionOut, EntryIn, EntryOut, VerdictIn, JuryScoreIn

router = APIRouter(prefix="/competitions", tags=["competitions"])


# ── helpers ──────────────────────────────────────────────────────────────────
def _entry_count(db: Session, comp_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(CompetitionEntry).where(CompetitionEntry.competition_id == comp_id)) or 0


def _comp_out(db: Session, comp: Competition) -> dict:
    out = CompetitionOut.model_validate(comp).model_dump()
    out["entry_count"] = _entry_count(db, comp.id)
    return out


def _avg_score(db: Session, entry_id: uuid.UUID) -> float | None:
    return db.scalar(
        select(func.avg(JuryVerdict.score)).where(JuryVerdict.entry_id == entry_id, JuryVerdict.score.isnot(None))
    )


def _artist_name(db: Session, user_id: uuid.UUID) -> str | None:
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == user_id))
    if kyc and kyc.name:
        return kyc.name
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    return prof.full_name if prof else None


def _enrich_entry(db: Session, entry: CompetitionEntry) -> dict:
    out = EntryOut.model_validate(entry).model_dump()
    out["artist_name"] = _artist_name(db, entry.user_id)
    out["image"] = entry.image_urls[0] if entry.image_urls else None
    avg = _avg_score(db, entry.id)
    out["avg_score"] = round(float(avg), 2) if avg is not None else None
    return out


def _promote_winner(db: Session, entry: CompetitionEntry):
    """Mark an entry as the winner and promote its artist to a verified seller."""
    entry.status = "winner"
    winner = db.get(User, entry.user_id)
    if winner and winner.profile:
        winner.profile.artist_status = "verified"
        winner.profile.role = "artist"
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == entry.user_id))
    if kyc:
        kyc.status = "verified"


# ── competitions ─────────────────────────────────────────────────────────────
@router.get("", response_model=list[CompetitionOut])
def list_competitions(db: Session = Depends(get_db)):
    comps = db.scalars(select(Competition).order_by(Competition.created_at.desc())).all()
    return [_comp_out(db, c) for c in comps]


@router.post("", response_model=CompetitionOut, status_code=201)
def create_competition(body: CompetitionIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    event_dt = None
    if body.event_date:
        try:
            event_dt = datetime.fromisoformat(body.event_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="event_date must be an ISO date (YYYY-MM-DD)")
    comp = Competition(
        title=body.title, month=body.month, description=body.description,
        event_date=event_dt, min_artists=body.min_artists or 0, status="open",
    )
    db.add(comp); db.commit(); db.refresh(comp)
    return _comp_out(db, comp)


@router.get("/live")
def live_competition(db: Session = Depends(get_db), me: User | None = Depends(get_optional_user)):
    """The currently-live competition + enriched entries for the public gallery popup.
    Returns null when nothing is live."""
    comp = db.scalar(select(Competition).where(Competition.status == "live").order_by(Competition.created_at.desc()))
    if not comp:
        return None
    entries = db.scalars(
        select(CompetitionEntry).where(CompetitionEntry.competition_id == comp.id).order_by(CompetitionEntry.created_at)
    ).all()
    is_jury = bool(me and me.profile and me.profile.role in ("jury", "admin"))
    my_scores: dict[str, int] = {}
    if is_jury and me:
        for v in db.scalars(select(JuryVerdict).where(JuryVerdict.recorded_by == me.id)).all():
            if v.score is not None:
                my_scores[str(v.entry_id)] = v.score
    return {
        "competition": _comp_out(db, comp),
        "entries": [_enrich_entry(db, e) for e in entries],
        "is_jury": is_jury,
        "my_scores": my_scores,
    }


@router.post("/{competition_id}/go-live")
def go_live(competition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")
    # Only one competition is live at a time — demote any other live ones to judging.
    for other in db.scalars(select(Competition).where(Competition.status == "live", Competition.id != comp.id)).all():
        other.status = "judging"
    comp.status = "live"
    db.commit()
    return {"ok": True, "status": comp.status}


@router.post("/{competition_id}/close")
def close_competition(competition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Close judging and auto-pick the winner = highest average jury score."""
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")
    entries = db.scalars(
        select(CompetitionEntry).where(CompetitionEntry.competition_id == comp.id).order_by(CompetitionEntry.created_at)
    ).all()
    if not entries:
        comp.status = "closed"; db.commit()
        return {"ok": True, "winner_entry_id": None}
    # Highest average score wins; ties / no scores fall back to the earliest entry.
    def keyf(e):
        avg = _avg_score(db, e.id)
        return (avg if avg is not None else -1.0)
    winner = max(entries, key=keyf)
    _promote_winner(db, winner)
    comp.status = "closed"
    db.commit()
    return {"ok": True, "winner_entry_id": str(winner.id)}


# ── entries ──────────────────────────────────────────────────────────────────
@router.post("/{competition_id}/entries", response_model=EntryOut, status_code=201)
def submit_entry(competition_id: uuid.UUID, body: EntryIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")
    if comp.status != "open":
        raise HTTPException(status_code=400, detail="Competition is not accepting entries")
    status = me.profile.artist_status if me.profile else "none"
    if status != "unverified":
        raise HTTPException(status_code=403, detail="Only competing (unverified) artists may enter. Apply as an artist first.")
    entry = CompetitionEntry(
        competition_id=competition_id, user_id=me.id, title=body.title,
        description=body.description, image_urls=body.image_urls or [], video_url=body.video_url,
    )
    db.add(entry); db.commit(); db.refresh(entry)
    return _enrich_entry(db, entry)


@router.get("/{competition_id}/entries", response_model=list[EntryOut])
def list_entries(competition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin", "jury"))):
    entries = db.scalars(
        select(CompetitionEntry).where(CompetitionEntry.competition_id == competition_id).order_by(CompetitionEntry.created_at)
    ).all()
    return [_enrich_entry(db, e) for e in entries]


@router.get("/entries/mine", response_model=list[EntryOut])
def my_entries(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    entries = db.scalars(select(CompetitionEntry).where(CompetitionEntry.user_id == me.id)).all()
    return [_enrich_entry(db, e) for e in entries]


# ── jury scoring ─────────────────────────────────────────────────────────────
@router.post("/entries/{entry_id}/score")
def score_entry(entry_id: uuid.UUID, body: JuryScoreIn, db: Session = Depends(get_db), me: User = Depends(require_role("jury", "admin"))):
    entry = db.get(CompetitionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not (1 <= body.score <= 5):
        raise HTTPException(status_code=400, detail="Score must be between 1 and 5")
    # One verdict per (entry, juror): update in place if it already exists.
    verdict = db.scalar(
        select(JuryVerdict).where(JuryVerdict.entry_id == entry_id, JuryVerdict.recorded_by == me.id)
    )
    if verdict:
        verdict.score = body.score
    else:
        name = me.profile.full_name if me.profile else None
        db.add(JuryVerdict(entry_id=entry_id, juror_name=name, score=body.score, recorded_by=me.id))
    if entry.status == "submitted":
        entry.status = "scored"
    comp = db.get(Competition, entry.competition_id)
    if comp and comp.status == "live":
        comp.status = "judging"
    db.commit()
    return {"ok": True, "avg_score": _avg_score(db, entry_id)}


# ── legacy admin verdict / manual winner (kept for compatibility) ─────────────
@router.post("/entries/{entry_id}/verdict")
def record_verdict(entry_id: uuid.UUID, body: VerdictIn, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    entry = db.get(CompetitionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.add(JuryVerdict(entry_id=entry_id, juror_name=body.juror_name, score=body.score, notes=body.notes, recorded_by=admin.id))
    entry.status = "scored"
    db.commit()
    return {"ok": True, "entry_status": entry.status}


@router.post("/entries/{entry_id}/winner")
def mark_winner(entry_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    entry = db.get(CompetitionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _promote_winner(db, entry)
    comp = db.get(Competition, entry.competition_id)
    if comp:
        comp.status = "closed"
    db.commit()
    return {"ok": True, "verified_user": str(entry.user_id)}
