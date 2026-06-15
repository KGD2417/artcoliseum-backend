"""Home-page news / announcements — public read (published only), admin CRUD,
plus an admin-only feed of art news pulled from a free external provider."""
import json
import re
import uuid
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_role
from ..models.user import User
from ..models.site import NewsItem
from ..schemas.extra import NewsOut

router = APIRouter(prefix="/news", tags=["news"])

# Editable fields accepted from the admin form.
_FIELDS = ("title", "summary", "image_url", "link_url", "published", "sort_order")

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str:
    return _TAG_RE.sub("", s or "").strip()


def _http_get_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ArtColiseum/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted provider URLs)
        return json.loads(resp.read().decode("utf-8"))


def _fetch_guardian(key: str) -> list[dict]:
    """The Guardian — free, generous, dedicated art-and-design coverage."""
    url = (
        "https://content.guardianapis.com/search?section=artanddesign"
        "&show-fields=thumbnail,trailText&order-by=newest&page-size=24&api-key="
        + urllib.parse.quote(key)
    )
    data = _http_get_json(url)
    out = []
    for a in (data.get("response", {}).get("results") or []):
        f = a.get("fields") or {}
        out.append({
            "title": a.get("webTitle"),
            "summary": _strip_html(f.get("trailText")),
            "image_url": f.get("thumbnail"),
            "link_url": a.get("webUrl"),
            "source": "The Guardian",
            "published_at": a.get("webPublicationDate"),
        })
    return out


def _fetch_gnews(key: str) -> list[dict]:
    q = urllib.parse.quote(settings.NEWS_API_QUERY or "art")
    url = f"https://gnews.io/api/v4/search?q={q}&lang=en&max=24&apikey={urllib.parse.quote(key)}"
    data = _http_get_json(url)
    out = []
    for a in (data.get("articles") or []):
        out.append({
            "title": a.get("title"),
            "summary": a.get("description"),
            "image_url": a.get("image"),
            "link_url": a.get("url"),
            "source": (a.get("source") or {}).get("name") or "GNews",
            "published_at": a.get("publishedAt"),
        })
    return out


def _fetch_newsdata(key: str) -> list[dict]:
    q = urllib.parse.quote(settings.NEWS_API_QUERY or "art")
    url = f"https://newsdata.io/api/1/news?apikey={urllib.parse.quote(key)}&q={q}&language=en"
    data = _http_get_json(url)
    out = []
    for a in (data.get("results") or []):
        out.append({
            "title": a.get("title"),
            "summary": a.get("description"),
            "image_url": a.get("image_url"),
            "link_url": a.get("link"),
            "source": a.get("source_id") or "NewsData",
            "published_at": a.get("pubDate"),
        })
    return out


_PROVIDERS = {"guardian": _fetch_guardian, "gnews": _fetch_gnews, "newsdata": _fetch_newsdata}


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


@router.get("/external")
def external_news(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Admin: latest art news from the configured free provider. Each item is
    flagged `already_added` if it has already been imported (by link), so the UI
    can show which ones are live. Nothing is saved until the admin imports it."""
    provider = (settings.NEWS_API_PROVIDER or "guardian").lower()
    key = settings.NEWS_API_KEY
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"No news API key configured. Set NEWS_API_KEY on the backend (provider: {provider}).",
        )
    fetch = _PROVIDERS.get(provider)
    if not fetch:
        raise HTTPException(status_code=400, detail=f"Unknown NEWS_API_PROVIDER '{provider}'. Use one of: {', '.join(_PROVIDERS)}.")
    try:
        items = fetch(key)
    except Exception as exc:  # network / provider / quota errors
        raise HTTPException(status_code=502, detail=f"Could not fetch news from {provider}: {exc}")

    items = [it for it in items if it.get("title") and it.get("link_url")]
    existing = set(db.scalars(select(NewsItem.link_url).where(NewsItem.link_url.is_not(None))).all())
    for it in items:
        it["already_added"] = it["link_url"] in existing
    return {"provider": provider, "items": items}


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
