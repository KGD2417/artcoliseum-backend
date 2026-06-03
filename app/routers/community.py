"""Community feed (posts/comments/likes/listings) + persistent chat rooms."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user
from ..models.user import User
from ..models.community import CommunityPost, PostComment, PostLike, ChatRoom, RoomMessage
from ..schemas.extra import PostIn, CommentIn, PostOut, RoomMessageIn

router = APIRouter(prefix="/community", tags=["community"])


def _post_out(db: Session, p: CommunityPost, me_id) -> PostOut:
    likes = db.scalar(select(func.count()).select_from(PostLike).where(PostLike.post_id == p.id)) or 0
    liked = bool(me_id and db.scalar(select(PostLike).where(PostLike.post_id == p.id, PostLike.user_id == me_id)))
    comments = db.scalars(select(PostComment).where(PostComment.post_id == p.id).order_by(PostComment.created_at)).all()
    return PostOut(
        id=p.id, user_id=p.user_id, community=p.community, author=p.author, type=p.type,
        text=p.text, images=p.images or [], video=p.video, title=p.title, condition=p.condition,
        location=p.location, created_at=p.created_at, likes=likes, liked=liked,
        comments=[{"author": c.author, "text": c.text} for c in comments],
    )


@router.get("/posts", response_model=list[PostOut])
def list_posts(community: str | None = Query(None), db: Session = Depends(get_db), me: User | None = Depends(get_optional_user)):
    stmt = select(CommunityPost).order_by(CommunityPost.created_at.desc())
    if community and community != "all":
        stmt = stmt.where(CommunityPost.community == community)
    return [_post_out(db, p, me.id if me else None) for p in db.scalars(stmt).all()]


@router.post("/posts", response_model=PostOut, status_code=201)
def create_post(body: PostIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    author = me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0]
    p = CommunityPost(
        user_id=me.id, community=body.community, author=author, type=body.type, text=body.text,
        images=body.images or [], video=body.video, title=body.title, condition=body.condition, location=body.location,
    )
    db.add(p); db.commit(); db.refresh(p)
    return _post_out(db, p, me.id)


@router.post("/posts/{post_id}/comments", response_model=PostOut)
def add_comment(post_id: uuid.UUID, body: CommentIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    p = db.get(CommunityPost, post_id)
    if not p:
        raise HTTPException(status_code=404, detail="Post not found")
    author = me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0]
    db.add(PostComment(post_id=post_id, user_id=me.id, author=author, text=body.text))
    db.commit()
    return _post_out(db, p, me.id)


@router.post("/posts/{post_id}/like", response_model=PostOut)
def toggle_like(post_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    p = db.get(CommunityPost, post_id)
    if not p:
        raise HTTPException(status_code=404, detail="Post not found")
    existing = db.scalar(select(PostLike).where(PostLike.post_id == post_id, PostLike.user_id == me.id))
    if existing:
        db.delete(existing)
    else:
        db.add(PostLike(post_id=post_id, user_id=me.id))
    db.commit()
    return _post_out(db, p, me.id)


@router.patch("/posts/{post_id}", response_model=PostOut)
def update_post(post_id: uuid.UUID, body: PostIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    p = db.get(CommunityPost, post_id)
    if not p:
        raise HTTPException(status_code=404, detail="Post not found")
    is_admin = bool(me.profile and me.profile.role == "admin")
    if p.user_id != me.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not your post")
    p.community = body.community; p.type = body.type; p.text = body.text
    p.images = body.images or []; p.video = body.video
    p.title = body.title; p.condition = body.condition; p.location = body.location
    db.commit(); db.refresh(p)
    return _post_out(db, p, me.id)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    p = db.get(CommunityPost, post_id)
    is_admin = bool(me.profile and me.profile.role == "admin")
    if p and (p.user_id == me.id or is_admin):
        db.delete(p); db.commit()
    return None


# ── Chat rooms ───────────────────────────────────────────────────────────────
@router.get("/rooms")
def list_rooms(db: Session = Depends(get_db)):
    rooms = db.scalars(select(ChatRoom).order_by(ChatRoom.name)).all()
    return [{"id": str(r.id), "slug": r.slug, "name": r.name, "description": r.description} for r in rooms]


@router.get("/rooms/{slug}/messages")
def room_messages(slug: str, db: Session = Depends(get_db)):
    room = db.scalar(select(ChatRoom).where(ChatRoom.slug == slug))
    if not room:
        return []
    msgs = db.scalars(select(RoomMessage).where(RoomMessage.room_id == room.id).order_by(RoomMessage.created_at)).all()
    return [{"id": str(m.id), "author": m.display_name, "text": m.text, "created_at": m.created_at.isoformat()} for m in msgs]


@router.post("/rooms/{slug}/messages", status_code=201)
def post_room_message(slug: str, body: RoomMessageIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    room = db.scalar(select(ChatRoom).where(ChatRoom.slug == slug))
    if not room:
        room = ChatRoom(slug=slug, name=slug.replace("-", " ").title())
        db.add(room); db.flush()
    name = me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0]
    m = RoomMessage(room_id=room.id, user_id=me.id, display_name=name, text=body.text)
    db.add(m); db.commit(); db.refresh(m)
    return {"id": str(m.id), "author": name, "text": m.text, "created_at": m.created_at.isoformat()}
