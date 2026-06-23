"""Community feed (posts/comments/likes/listings/auctions) + persistent chat rooms."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, get_optional_user, require_role
from ..models.user import User, Profile
from ..models.community import Community, CommunityPost, PostComment, PostLike, ChatRoom, RoomMessage, Bid
from ..schemas.extra import PostIn, CommentIn, PostOut, RoomMessageIn, CommunityIn, CommunityOut, BidIn

router = APIRouter(prefix="/community", tags=["community"])


def _parse_dt(v):
    """ISO string (incl. trailing 'Z') or datetime → aware datetime, else None."""
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _display_name(me: User) -> str:
    return me.profile.full_name if (me.profile and me.profile.full_name) else me.email.split("@")[0]


def _top_bid(db: Session, post_id) -> Bid | None:
    """Highest offer on a post; ties broken by who bid first (cannot happen — bids must rise)."""
    return db.scalar(
        select(Bid).where(Bid.post_id == post_id).order_by(Bid.amount.desc(), Bid.created_at.asc())
    )


def _auction_ended(p: CommunityPost) -> bool:
    if not p.is_auction:
        return False
    if p.auction_closed:
        return True
    if p.auction_ends_at:
        ends = p.auction_ends_at
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= ends
    return False


def _finalize_if_ended(db: Session, p: CommunityPost) -> None:
    """Lazily lock in the winner once an auction's deadline has passed (no cron needed)."""
    if p.is_auction and not p.auction_closed and _auction_ended(p):
        top = _top_bid(db, p.id)
        p.auction_closed = True
        p.winner_user_id = top.user_id if top else None
        db.commit()


# Seeded the first time the table is read so the feed never looks empty.
_DEFAULT_COMMUNITIES = [
    ("painting",    "Painting",     "Oil, acrylic, watercolour and all painted works", "#8B4513"),
    ("sculpture",   "Sculpture",    "Clay, bronze, marble and mixed 3D forms",         "#4A7C59"),
    ("digital",     "Digital Art",  "Digital, generative, NFT and new media",          "#2C5A8E"),
    ("photography", "Photography",  "Fine art and documentary photography",            "#6E2C4A"),
    ("mixed",       "Mixed Media",  "Collage, installation and experimental",          "#4A2C7E"),
    ("marketplace", "Marketplace",  "Buy, sell and trade original artworks",           "#B87333"),
    ("general",     "General",      "Art news, events and open conversations",         "#2C8E6E"),
]


def _slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (s or "").lower()).strip("-") or "community"


@router.get("/communities", response_model=list[CommunityOut])
def list_communities(db: Session = Depends(get_db)):
    rows = db.scalars(select(Community).order_by(Community.name)).all()
    if not rows:
        for slug, name, desc, color in _DEFAULT_COMMUNITIES:
            db.add(Community(slug=slug, name=name, description=desc, color=color))
        db.commit()
        rows = db.scalars(select(Community).order_by(Community.name)).all()
    return list(rows)


@router.post("/communities", response_model=CommunityOut, status_code=201)
def create_community(body: CommunityIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    slug = _slugify(body.slug or body.name)
    if db.scalar(select(Community).where(Community.slug == slug)):
        raise HTTPException(status_code=409, detail="A community with this name already exists")
    c = Community(slug=slug, name=body.name, description=body.description, color=body.color or "#D4AF37")
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.delete("/communities/{slug}", status_code=204)
def delete_community(slug: str, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    c = db.scalar(select(Community).where(Community.slug == slug))
    if c:
        db.delete(c); db.commit()
    return None


def _f(v):
    return float(v) if v is not None else None


def _post_out(db: Session, p: CommunityPost, me_id) -> PostOut:
    # Auction posts past their deadline are finalised here before we read state.
    _finalize_if_ended(db, p)

    likes = db.scalar(select(func.count()).select_from(PostLike).where(PostLike.post_id == p.id)) or 0
    liked = bool(me_id and db.scalar(select(PostLike).where(PostLike.post_id == p.id, PostLike.user_id == me_id)))
    comments = db.scalars(select(PostComment).where(PostComment.post_id == p.id).order_by(PostComment.created_at)).all()
    # Merge the legacy single `video` into the `videos` list for older rows.
    videos = list(p.videos or [])
    if p.video and p.video not in videos:
        videos = [p.video, *videos]

    # Auction enrichment.
    bid_rows, current_bid, bid_count, top_id, winner_name = [], None, 0, None, None
    if p.is_auction:
        rows = db.scalars(
            select(Bid).where(Bid.post_id == p.id).order_by(Bid.amount.desc(), Bid.created_at.asc())
        ).all()
        bid_count = len(rows)
        bid_rows = [
            {"user_id": str(b.user_id), "bidder": b.bidder_name, "amount": _f(b.amount),
             "created_at": b.created_at.isoformat()}
            for b in rows[:50]
        ]
        if rows:
            current_bid = _f(rows[0].amount)
            top_id = rows[0].user_id
        if p.winner_user_id and rows:
            winner_name = next((b.bidder_name for b in rows if b.user_id == p.winner_user_id), rows[0].bidder_name)

    author_avatar = db.scalar(
        select(Profile.avatar_url).where(Profile.user_id == p.user_id)
    )

    return PostOut(
        id=p.id, user_id=p.user_id, community=p.community, author=p.author,
        author_avatar=author_avatar, type=p.type,
        text=p.text, images=p.images or [], video=p.video, videos=videos, title=p.title, condition=p.condition,
        location=p.location, created_at=p.created_at, likes=likes, liked=liked,
        comments=[{"author": c.author, "text": c.text} for c in comments],
        is_auction=p.is_auction, starting_bid=_f(p.starting_bid), min_increment=_f(p.min_increment),
        auction_ends_at=p.auction_ends_at, auction_closed=p.auction_closed, auction_ended=_auction_ended(p),
        winner_user_id=p.winner_user_id, winner_name=winner_name,
        current_bid=current_bid, bid_count=bid_count, top_bidder_id=top_id, bids=bid_rows,
    )


def _apply_auction_fields(p: CommunityPost, body: PostIn) -> None:
    """Set auction config from the payload. Only listings can be auctions."""
    is_auction = bool(body.is_auction) and body.type == "listing"
    p.is_auction = is_auction
    if is_auction:
        p.starting_bid = body.starting_bid
        p.min_increment = body.min_increment or 0
        p.auction_ends_at = _parse_dt(body.auction_ends_at)
    else:
        p.starting_bid = None
        p.min_increment = 0
        p.auction_ends_at = None


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
        images=body.images or [], video=body.video, videos=body.videos or [],
        title=body.title, condition=body.condition, location=body.location,
    )
    _apply_auction_fields(p, body)
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
    p.images = body.images or []; p.video = body.video; p.videos = body.videos or []
    p.title = body.title; p.condition = body.condition; p.location = body.location
    # Don't let auction terms change once people have started bidding.
    has_bids = bool(db.scalar(select(func.count()).select_from(Bid).where(Bid.post_id == p.id)))
    if not has_bids:
        _apply_auction_fields(p, body)
    db.commit(); db.refresh(p)
    return _post_out(db, p, me.id)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    p = db.get(CommunityPost, post_id)
    is_admin = bool(me.profile and me.profile.role == "admin")
    if p and (p.user_id == me.id or is_admin):
        db.delete(p); db.commit()
    return None


# ── Auction bidding ──────────────────────────────────────────────────────────
@router.get("/posts/{post_id}/bids")
def list_bids(post_id: uuid.UUID, db: Session = Depends(get_db)):
    """Public bid history for an auction listing, highest first."""
    rows = db.scalars(
        select(Bid).where(Bid.post_id == post_id).order_by(Bid.amount.desc(), Bid.created_at.asc())
    ).all()
    return [
        {"user_id": str(b.user_id), "bidder": b.bidder_name, "amount": float(b.amount),
         "created_at": b.created_at.isoformat()}
        for b in rows
    ]


@router.post("/posts/{post_id}/bids", response_model=PostOut)
def place_bid(post_id: uuid.UUID, body: BidIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    # Lock the listing row for this transaction so simultaneous bids serialise:
    # the second bidder blocks until the first commits, then re-reads the now
    # higher top bid and is validated against it — so two equal "winning" bids
    # can never both be accepted. (Postgres FOR UPDATE; a no-op but still safe
    # on SQLite, which serialises writes globally.)
    p = db.scalar(select(CommunityPost).where(CommunityPost.id == post_id).with_for_update())
    if not p:
        raise HTTPException(status_code=404, detail="Post not found")
    if not p.is_auction:
        raise HTTPException(status_code=400, detail="This listing is not an auction")
    if _auction_ended(p):
        raise HTTPException(status_code=400, detail="This auction has ended")
    if p.user_id == me.id:
        raise HTTPException(status_code=403, detail="You cannot bid on your own listing")

    amount = float(body.amount or 0)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Enter a valid bid amount")

    top = _top_bid(db, p.id)
    min_inc = float(p.min_increment or 0)
    if top:
        base = float(top.amount)
        if min_inc > 0 and amount < base + min_inc:
            raise HTTPException(status_code=400, detail=f"Bid must be at least ₹{base + min_inc:,.0f} (current + increment)")
        if min_inc <= 0 and amount <= base:
            raise HTTPException(status_code=400, detail=f"Bid must be higher than the current bid of ₹{base:,.0f}")
    else:
        start = float(p.starting_bid or 0)
        if amount < start:
            raise HTTPException(status_code=400, detail=f"First bid must be at least the starting bid of ₹{start:,.0f}")

    db.add(Bid(post_id=p.id, user_id=me.id, bidder_name=_display_name(me), amount=amount))
    db.commit(); db.refresh(p)
    return _post_out(db, p, me.id)


@router.post("/posts/{post_id}/close", response_model=PostOut)
def close_auction(post_id: uuid.UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Seller (or admin) ends the auction now and awards the highest bidder."""
    # Lock the row so closing waits for any in-flight bid to commit first,
    # guaranteeing we award the true highest bid (no lost last-second bid).
    p = db.scalar(select(CommunityPost).where(CommunityPost.id == post_id).with_for_update())
    if not p:
        raise HTTPException(status_code=404, detail="Post not found")
    if not p.is_auction:
        raise HTTPException(status_code=400, detail="This listing is not an auction")
    is_admin = bool(me.profile and me.profile.role == "admin")
    if p.user_id != me.id and not is_admin:
        raise HTTPException(status_code=403, detail="Only the seller can end this auction")
    top = _top_bid(db, p.id)
    p.auction_closed = True
    p.winner_user_id = top.user_id if top else None
    db.commit(); db.refresh(p)
    return _post_out(db, p, me.id)


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
        # Only admins may spin up a new room; everyone else posts in existing ones.
        if not (me.profile and me.profile.role == "admin"):
            raise HTTPException(status_code=403, detail="Only admins can create new rooms")
        room = ChatRoom(slug=slug, name=slug.replace("-", " ").title())
        db.add(room); db.flush()
    name = me.profile.full_name if me.profile and me.profile.full_name else me.email.split("@")[0]
    m = RoomMessage(room_id=room.id, user_id=me.id, display_name=name, text=body.text)
    db.add(m); db.commit(); db.refresh(m)
    return {"id": str(m.id), "author": name, "text": m.text, "created_at": m.created_at.isoformat()}
