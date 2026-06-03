"""Monthly competition: unverified artists enter; admin records jury verdicts and
picks the winner, who becomes a VERIFIED artist allowed to sell."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.competition import Competition, CompetitionEntry, JuryVerdict, ArtistKyc
from ..schemas.extra import CompetitionIn, CompetitionOut, EntryIn, EntryOut, VerdictIn

router = APIRouter(prefix="/competitions", tags=["competitions"])


@router.get("", response_model=list[CompetitionOut])
def list_competitions(db: Session = Depends(get_db)):
    return list(db.scalars(select(Competition).order_by(Competition.created_at.desc())).all())


@router.post("", response_model=CompetitionOut, status_code=201)
def create_competition(body: CompetitionIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    comp = Competition(title=body.title, month=body.month, description=body.description, status="open")
    db.add(comp); db.commit(); db.refresh(comp)
    return comp


@router.post("/{competition_id}/entries", response_model=EntryOut, status_code=201)
def submit_entry(competition_id: uuid.UUID, body: EntryIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    comp = db.get(Competition, competition_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Competition not found")
    if comp.status != "open":
        raise HTTPException(status_code=400, detail="Competition is not accepting entries")
    status = me.profile.artist_status if me.profile else "none"
    if status not in ("unverified", "verified"):
        raise HTTPException(status_code=403, detail="Apply as an artist (KYC) before entering")
    entry = CompetitionEntry(
        competition_id=competition_id, user_id=me.id, title=body.title,
        description=body.description, image_urls=body.image_urls or [], video_url=body.video_url,
    )
    db.add(entry); db.commit(); db.refresh(entry)
    return entry


@router.get("/{competition_id}/entries", response_model=list[EntryOut])
def list_entries(competition_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return list(db.scalars(
        select(CompetitionEntry).where(CompetitionEntry.competition_id == competition_id).order_by(CompetitionEntry.created_at)
    ).all())


@router.get("/entries/mine", response_model=list[EntryOut])
def my_entries(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return list(db.scalars(select(CompetitionEntry).where(CompetitionEntry.user_id == me.id)).all())


@router.post("/entries/{entry_id}/verdict")
def record_verdict(entry_id: uuid.UUID, body: VerdictIn, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    entry = db.get(CompetitionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.add(JuryVerdict(entry_id=entry_id, juror_name=body.juror_name, score=body.score, notes=body.notes, recorded_by=admin.id))
    entry.status = "scored"
    comp = db.get(Competition, entry.competition_id)
    if comp and comp.status == "open":
        comp.status = "judging"
    db.commit()
    return {"ok": True, "entry_status": entry.status}


@router.post("/entries/{entry_id}/winner")
def mark_winner(entry_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    entry = db.get(CompetitionEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry.status = "winner"
    # promote the winning artist
    winner = db.get(User, entry.user_id)
    if winner and winner.profile:
        winner.profile.artist_status = "verified"
        winner.profile.role = "artist"
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == entry.user_id))
    if kyc:
        kyc.status = "verified"
    comp = db.get(Competition, entry.competition_id)
    if comp:
        comp.status = "closed"
    db.commit()
    return {"ok": True, "verified_user": str(entry.user_id)}
