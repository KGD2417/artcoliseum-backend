"""Editable site content (Privacy Policy, etc.) — public read, admin write."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models.user import User
from ..models.site import SiteSetting

router = APIRouter(prefix="/site", tags=["site"])


def _get(db: Session, key: str):
    s = db.scalar(select(SiteSetting).where(SiteSetting.key == key))
    return s.value if (s and s.value) else None


def _set(db: Session, key: str, value: dict):
    s = db.scalar(select(SiteSetting).where(SiteSetting.key == key))
    if s:
        s.value = value
    else:
        db.add(SiteSetting(key=key, value=value))
    db.commit()
    return value


@router.get("/privacy")
def get_privacy(db: Session = Depends(get_db)):
    """Public: the editable Privacy Policy ({sections:[{title,body}], updated}).
    Returns null when unset → the frontend shows its built-in default."""
    return _get(db, "privacy")


@router.put("/privacy")
def set_privacy(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _set(db, "privacy", body)


@router.get("/preservation")
def get_preservation(db: Session = Depends(get_db)):
    """Public: the homepage Preservation-section images ({images:[url,...]}).
    Returns null when unset → the frontend shows its built-in defaults."""
    return _get(db, "preservation")


@router.put("/preservation")
def set_preservation(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _set(db, "preservation", body)


@router.get("/art-of-season")
def get_art_of_season(db: Session = Depends(get_db)):
    """Public: the homepage "Art of Seasons" showcase, separately curated by the
    admin ({items:[{image,title,link}]}). Returns null when unset → the frontend
    falls back to featured artworks."""
    return _get(db, "art_of_season")


@router.put("/art-of-season")
def set_art_of_season(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    return _set(db, "art_of_season", body)
