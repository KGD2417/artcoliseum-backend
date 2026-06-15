"""Chat history, sending, read receipts, and the peer directory."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User, Profile
from ..models.chat import ChatMessage, ChatRead
from ..schemas.chat import ChatMessageOut, ChatMessageIn, ChatReadIn, PeerOut
from ..websocket import manager

router = APIRouter(prefix="/chat", tags=["chat"])


def _is_admin(user: User) -> bool:
    return bool(user.profile and user.profile.role == "admin")


def _peer_ids(key: str) -> set[str]:
    # "peer:<a>:<b>" → {a, b}
    parts = key.split(":")
    return set(parts[1:3]) if len(parts) >= 3 else set()


@router.get("/conversation/{conversation_key}", response_model=list[ChatMessageOut])
def conversation(
    conversation_key: str,
    user_id: uuid.UUID | None = Query(None),  # admin may scope to a specific user
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    stmt = select(ChatMessage).where(ChatMessage.conversation_key == conversation_key)
    if conversation_key.startswith("peer:"):
        if str(me.id) not in _peer_ids(conversation_key) and not _is_admin(me):
            raise HTTPException(status_code=403, detail="Not a participant")
        # peer threads are scoped by key only (both sides' rows)
    elif _is_admin(me):
        # Admins may scope to one customer's thread; without a user_id they see
        # every message under this key (so an enquiry is never an empty guess).
        if user_id is not None:
            stmt = stmt.where(ChatMessage.user_id == user_id)
    else:
        stmt = stmt.where(ChatMessage.user_id == me.id)
    stmt = stmt.order_by(ChatMessage.created_at)
    return list(db.scalars(stmt).all())


@router.get("/mine", response_model=list[ChatMessageOut])
def mine(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    stmt = select(ChatMessage).where(ChatMessage.user_id == me.id).order_by(ChatMessage.created_at)
    return list(db.scalars(stmt).all())


@router.get("/admin/all", response_model=list[ChatMessageOut])
def admin_all(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if not _is_admin(me):
        raise HTTPException(status_code=403, detail="Admins only")
    return list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)).all())


@router.get("/unread")
def unread(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    msgs = db.scalars(
        select(ChatMessage).where(ChatMessage.user_id == me.id, ChatMessage.sender != "me")
    ).all()
    reads = db.scalars(select(ChatRead).where(ChatRead.user_id == me.id)).all()
    read_map = {r.conversation_key: r.last_read_at for r in reads}
    count = 0
    for m in msgs:
        last = read_map.get(m.conversation_key)
        if last is None or m.created_at > last:
            count += 1
    return {"unread": count}


@router.post("", response_model=ChatMessageOut, status_code=201)
async def send(body: ChatMessageIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    key = body.conversation_key
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")

    recipients: set[str] = set()

    if key.startswith("peer:"):
        ids = _peer_ids(key)
        if str(me.id) not in ids:
            raise HTTPException(status_code=403, detail="Not a participant")
        owner_id = me.id
        sender = "me"
        recipients = ids  # both peers
    elif body.sender != "me" and body.target_user_id is not None:
        # Admin replying on behalf of an artist/curator/bot.
        if not _is_admin(me):
            raise HTTPException(status_code=403, detail="Admins only")
        owner_id = body.target_user_id
        sender = body.sender
        recipients = {str(owner_id)}
    else:
        # User writing in their own thread (sender "me" or seeding "bot" greeting).
        owner_id = me.id
        sender = body.sender if body.sender in ("me", "bot") else "me"
        recipients = {str(owner_id)}

    msg = ChatMessage(user_id=owner_id, conversation_key=key, sender=sender, text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)

    out = ChatMessageOut.model_validate(msg).model_dump()
    await manager.broadcast(out, recipients, notify_admins=True)
    return msg


@router.get("/reads")
def reads(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    rows = db.scalars(select(ChatRead).where(ChatRead.user_id == me.id)).all()
    return [{"conversation_key": r.conversation_key, "last_read_at": r.last_read_at} for r in rows]


@router.post("/read", status_code=204)
def mark_read(body: ChatReadIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    row = db.scalar(
        select(ChatRead).where(
            ChatRead.user_id == me.id, ChatRead.conversation_key == body.conversation_key
        )
    )
    if row:
        row.last_read_at = func.now()
    else:
        db.add(ChatRead(user_id=me.id, conversation_key=body.conversation_key))
    db.commit()
    return None


@router.get("/names")
def names(ids: str = Query(""), db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Resolve a comma-separated list of user IDs to display names (for labelling
    direct-message threads with the other person's name instead of 'Direct message')."""
    out: dict[str, str] = {}
    for raw in (ids or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            uid = uuid.UUID(raw)
        except ValueError:
            continue
        u = db.get(User, uid)
        if not u:
            continue
        out[str(uid)] = (u.profile.full_name if (u.profile and u.profile.full_name) else u.email.split("@")[0])
    return out


@router.get("/peers", response_model=list[PeerOut])
def peers(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    if not (me.profile and me.profile.role in ("artist", "admin")):
        raise HTTPException(status_code=403, detail="Artists only")
    rows = db.scalars(
        select(Profile).where(Profile.role == "artist", Profile.user_id != me.id)
    ).all()
    return [PeerOut(id=p.user_id, full_name=p.full_name, avatar_url=p.avatar_url) for p in rows]
