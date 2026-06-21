"""Visitor tracking — record page views (IP + geo + device + session journey)
and expose a traffic overview to admins so visits are fully traceable."""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..deps import get_optional_user, require_role
from ..models.user import User
from ..models.analytics import Visit

router = APIRouter(prefix="/traffic", tags=["traffic"])

# Per-process IP→geo cache so repeat visitors don't trigger repeat lookups.
_geo_cache: dict[str, dict] = {}


def _client_ip(request: Request) -> str | None:
    """Real client IP, honouring the proxy chain (Railway/Vercel set XFF)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else None


def _is_private(ip: str) -> bool:
    return (
        not ip
        or ip in ("127.0.0.1", "::1", "localhost")
        or ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                          "172.19.", "172.2", "172.30.", "172.31.", "fc", "fd"))
    )


def _parse_ua(ua: str) -> tuple[str, str, str]:
    """Lightweight user-agent → (device, browser, os). No external dependency."""
    u = (ua or "").lower()
    # Device
    if any(b in u for b in ("bot", "spider", "crawl", "slurp")):
        device = "Bot"
    elif "ipad" in u or ("tablet" in u and "mobile" not in u):
        device = "Tablet"
    elif any(m in u for m in ("mobi", "iphone", "android")) and "ipad" not in u:
        device = "Mobile"
    else:
        device = "Desktop"
    # Browser (order matters: Edge/Chrome share tokens)
    if "edg" in u:
        browser = "Edge"
    elif "opr" in u or "opera" in u:
        browser = "Opera"
    elif "chrome" in u or "crios" in u:
        browser = "Chrome"
    elif "firefox" in u or "fxios" in u:
        browser = "Firefox"
    elif "safari" in u:
        browser = "Safari"
    else:
        browser = "Other"
    # OS
    if "windows" in u:
        os_name = "Windows"
    elif "iphone" in u or "ipad" in u or "ios" in u:
        os_name = "iOS"
    elif "mac os" in u or "macintosh" in u:
        os_name = "macOS"
    elif "android" in u:
        os_name = "Android"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "Other"
    return device, browser, os_name


def _resolve_geo(ip: str) -> dict:
    """Best-effort IP geolocation (cached). Returns {country, city} or {}."""
    if not ip or _is_private(ip):
        return {}
    if ip in _geo_cache:
        return _geo_cache[ip]
    out: dict = {}
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,city"
        with urllib.request.urlopen(url, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            out = {"country": data.get("country"), "city": data.get("city")}
    except Exception:
        out = {}
    _geo_cache[ip] = out
    return out


def _geocode_visit(visit_id, ip: str) -> None:
    """Background task: resolve geo for a freshly-stored visit, then persist it."""
    geo = _resolve_geo(ip)
    if not geo:
        return
    db = SessionLocal()
    try:
        v = db.get(Visit, visit_id)
        if v:
            v.country = geo.get("country")
            v.city = geo.get("city")
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@router.post("/track", status_code=202)
def track(
    body: dict,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Public: record a single page view. Body: {path, referrer?, session_id?}.
    IP, user-agent and (optionally) the signed-in user are captured server-side.
    Geo is resolved asynchronously so the response stays fast."""
    path = (body.get("path") or "").strip()[:512]
    if not path:
        return {"ok": False}
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    device, browser, os_name = _parse_ua(ua)
    v = Visit(
        session_id=(body.get("session_id") or None),
        user_id=(user.id if user else None),
        path=path,
        referrer=(body.get("referrer") or None),
        ip=ip,
        user_agent=ua,
        device=device,
        browser=browser,
        os=os_name,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    if ip and not _is_private(ip):
        background.add_task(_geocode_visit, v.id, ip)
    return {"ok": True}


@router.get("/overview")
def overview(
    days: int = 30,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Admin: full traffic picture — totals, top pages/countries, device &
    browser mix, recent visits, and per-visitor session journeys."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    base = select(Visit).where(Visit.created_at >= since)

    def _group(col, limit=12):
        rows = db.execute(
            select(col, func.count())
            .where(Visit.created_at >= since)
            .group_by(col)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
        return [{"label": (r[0] or "Unknown"), "count": r[1]} for r in rows]

    total = db.scalar(select(func.count()).select_from(Visit).where(Visit.created_at >= since)) or 0
    unique_ips = db.scalar(select(func.count(func.distinct(Visit.ip))).where(Visit.created_at >= since)) or 0
    unique_sessions = db.scalar(
        select(func.count(func.distinct(Visit.session_id))).where(Visit.created_at >= since)
    ) or 0
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    last_24h = db.scalar(select(func.count()).select_from(Visit).where(Visit.created_at >= day_ago)) or 0

    # Recent visits (most recent first), with the user's email when signed in.
    recent_rows = list(db.scalars(base.order_by(Visit.created_at.desc()).limit(300)).all())
    user_ids = {v.user_id for v in recent_rows if v.user_id}
    emails: dict = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            emails[u.id] = u.email

    def _fmt(v: Visit) -> dict:
        return {
            "id": str(v.id),
            "time": v.created_at.isoformat() if v.created_at else None,
            "path": v.path,
            "referrer": v.referrer,
            "ip": v.ip,
            "country": v.country,
            "city": v.city,
            "device": v.device,
            "browser": v.browser,
            "os": v.os,
            "session_id": v.session_id,
            "user_email": emails.get(v.user_id),
        }

    recent = [_fmt(v) for v in recent_rows]

    # Journeys: group the recent visits by session into an ordered page sequence.
    journeys: dict = {}
    for v in reversed(recent_rows):  # oldest→newest so each journey reads in order
        key = v.session_id or f"ip:{v.ip}"
        j = journeys.setdefault(key, {
            "session_id": v.session_id,
            "ip": v.ip,
            "country": v.country,
            "city": v.city,
            "device": v.device,
            "user_email": emails.get(v.user_id),
            "started_at": v.created_at.isoformat() if v.created_at else None,
            "pages": [],
        })
        if emails.get(v.user_id):
            j["user_email"] = emails.get(v.user_id)
        if v.country and not j["country"]:
            j["country"] = v.country
        j["pages"].append({"path": v.path, "time": v.created_at.isoformat() if v.created_at else None})
        j["last_at"] = v.created_at.isoformat() if v.created_at else None

    journey_list = sorted(
        journeys.values(), key=lambda j: j.get("last_at") or "", reverse=True
    )[:60]
    for j in journey_list:
        j["count"] = len(j["pages"])

    return {
        "totals": {
            "visits": total,
            "unique_ips": unique_ips,
            "unique_sessions": unique_sessions,
            "last_24h": last_24h,
            "days": days,
        },
        "top_pages": _group(Visit.path),
        "top_countries": _group(Visit.country),
        "devices": _group(Visit.device, 6),
        "browsers": _group(Visit.browser, 8),
        "recent": recent,
        "journeys": journey_list,
    }
