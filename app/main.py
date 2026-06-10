"""Art Coliseum FastAPI backend — application entrypoint."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from . import models  # noqa: F401  (ensures all tables are registered on Base)
from .routers import (
    auth, uploads, categories, artworks, artists, chat,
    enquiries, cart, orders, deliveries, reviews,
    competitions, community, events, support, admin,
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
