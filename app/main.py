"""Art Coliseum FastAPI backend — application entrypoint."""
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import settings
from .ratelimit import limiter
from .database import Base, engine
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from . import models  # noqa: F401  (ensures all tables are registered on Base)
from .routers import (
    auth, uploads, categories, artworks, artists, chat,
    enquiries, cart, orders, deliveries, reviews,
    competitions, community, events, support, admin, exhibitions,
    testimonials, news, ai, notifications,
)
from .database import SessionLocal
from .models.user import User
from .security import decode_token
from .websocket import manager

# Dev convenience: create any missing tables on startup.
# (Phase-by-phase schema growth; swap to Alembic migrations before production.)
Base.metadata.create_all(bind=engine)


def _run_lightweight_migrations() -> None:
    """Add columns that were introduced after a table already existed.

    create_all() never ALTERs existing tables, so newly-added columns need a
    one-off, idempotent ADD COLUMN IF NOT EXISTS. Keep these Postgres-safe.
    """
    from sqlalchemy import text
    statements = [
        # community_posts.videos — multiple-video support for posts.
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS videos JSONB DEFAULT '[]'::jsonb",
        # categories — admin-managed page content (hero/card image, tagline,
        # description, detail-page tabs, pioneers list).
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS image_url VARCHAR",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS tagline VARCHAR",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS tabs JSONB",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS pioneers JSONB",
        # artworks.rejection_reason — feedback when an admin rejects a submission.
        "ALTER TABLE artworks ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        # artworks structured size (base_dimensions is the derived display string).
        "ALTER TABLE artworks ADD COLUMN IF NOT EXISTS width NUMERIC(10,2)",
        "ALTER TABLE artworks ADD COLUMN IF NOT EXISTS height NUMERIC(10,2)",
        "ALTER TABLE artworks ADD COLUMN IF NOT EXISTS depth NUMERIC(10,2)",
        # cart_items — persist the buyer's chosen customization for display.
        "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS custom_width NUMERIC(10,2)",
        "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS custom_height NUMERIC(10,2)",
        "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS custom_depth NUMERIC(10,2)",
        "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS custom_unit VARCHAR",
        "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS options JSONB",
        # events.maps_url — admin-supplied Google Maps link for the venue.
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS maps_url VARCHAR",
        # artworks.exhibition_id — exhibition-only pieces (excluded from the store).
        "ALTER TABLE artworks ADD COLUMN IF NOT EXISTS exhibition_id UUID",
        # community_posts — marketplace listings can run as auctions (highest bid wins).
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS is_auction BOOLEAN DEFAULT FALSE",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS starting_bid NUMERIC(12,2)",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS min_increment NUMERIC(12,2) DEFAULT 0",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS auction_ends_at TIMESTAMPTZ",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS auction_closed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE community_posts ADD COLUMN IF NOT EXISTS winner_user_id UUID",
        # contact / support attachments — photos & videos sent for context.
        "ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS images JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS videos JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE contact_messages ADD COLUMN IF NOT EXISTS phone VARCHAR",
        "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS images JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS videos JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS phone VARCHAR",
        # artist_kyc.rejection_reason — feedback shown to a rejected applicant.
        "ALTER TABLE artist_kyc ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        # order_items — artist sales dashboard: who made it, the buyer's custom
        # spec, and the artist's own direct-ship dispatch state.
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS artist_id VARCHAR",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS options JSONB",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS custom_width NUMERIC(10,2)",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS custom_height NUMERIC(10,2)",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS custom_depth NUMERIC(10,2)",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS custom_unit VARCHAR",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS artist_dispatched BOOLEAN DEFAULT FALSE",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS artist_tracking JSONB",
        # profiles.pickup_address — artist's ship-from origin for direct fulfillment.
        "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS pickup_address JSONB",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as exc:  # pragma: no cover - best-effort dev migration
                print(f"[migration] skipped: {stmt!r} ({exc})")


_run_lightweight_migrations()

app = FastAPI(title="Art Coliseum API", version="0.1.0")

_origins_raw = [o.strip() for o in settings.FRONTEND_ORIGIN.split(",") if o.strip()]
_wildcard = "*" in _origins_raw
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _wildcard else _origins_raw,
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-client rate limiting (abuse protection). 600/min global default, with
# tighter caps on auth routes (see app/routers/auth.py).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# Baseline security headers on every response.
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    return resp

# Serve uploaded files statically at /uploads/...
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(auth.router)
app.include_router(uploads.router)
app.include_router(categories.router)
app.include_router(artworks.router)
app.include_router(artists.router)
app.include_router(chat.router)
app.include_router(enquiries.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(deliveries.router)
app.include_router(reviews.router)
app.include_router(competitions.router)
app.include_router(community.router)
app.include_router(events.router)
app.include_router(support.router)
app.include_router(admin.router)
app.include_router(exhibitions.router)
app.include_router(testimonials.router)
app.include_router(news.router)
app.include_router(ai.router)
app.include_router(notifications.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


print("WEBSOCKET ROUTE REGISTERED")

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, token: str = ""):
    """Live chat socket. Auth via ?token=<access JWT>."""
    payload = decode_token(token, expected_type="access")
    if not payload:
        await websocket.close(code=1008)
        return
    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
        if not user:
            await websocket.close(code=1008)
            return
        is_admin = bool(user.profile and user.profile.role == "admin")
    finally:
        db.close()

    await manager.connect(websocket, str(user.id), is_admin)
    try:
        while True:
            await websocket.receive_text()  # keepalive; client isn't required to send
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
