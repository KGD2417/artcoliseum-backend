"""Home-page news / announcements — public read (published only), admin CRUD."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models.user import User
from ..models.site import NewsItem
from ..schemas.extra import NewsOut

router = APIRouter(prefix="/news", tags=["news"])

# Editable fields accepted from the admin form.
_FIELDS = ("title", "summary", "image_url", "link_url", "published", "sort_order")


def _ordered(query):
    # Manual order first (lower = earlier), then newest by date.
    return query.order_by(NewsItem.sort_order, NewsItem.created_at.desc())


@router.get("", response_model=list[NewsOut])
def list_news(db: Session = Depends(get_db)):
    """Public: only published news items."""
    return db.scalars(_ordered(select(NewsItem).where(NewsItem.published.is_(True)))).all()


@router.get("/all", response_model=list[NewsOut])
def list_all(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Admin: every news item, including unpublished ones."""
    return db.scalars(_ordered(select(NewsItem))).all()


@router.post("", response_model=NewsOut, status_code=201)
def create_news(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    if not body.get("title"):
        raise HTTPException(status_code=422, detail="Title is required")
    n = NewsItem(
        title=body["title"],
        summary=body.get("summary"),
        image_url=body.get("image_url"),
        link_url=body.get("link_url"),
        published=bool(body.get("published", True)),
        sort_order=int(body.get("sort_order") or 0),
    )
    db.add(n); db.commit(); db.refresh(n)
    return n


@router.patch("/{news_id}", response_model=NewsOut)
def update_news(news_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    n = db.get(NewsItem, news_id)
    if not n:
        raise HTTPException(status_code=404, detail="News item not found")
    for f in _FIELDS:
        if f in body:
            setattr(n, f, body[f])
    db.commit(); db.refresh(n)
    return n


@router.delete("/{news_id}", status_code=204)
def delete_news(news_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    n = db.get(NewsItem, news_id)
    if n:
        db.delete(n); db.commit()
    return None
