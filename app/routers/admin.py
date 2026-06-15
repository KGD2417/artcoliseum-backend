"""Admin control-panel aggregates: stats, artist KYC, role management."""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as _xesc

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models.user import User, Profile
from ..models.catalog import Artwork, Artist
from ..models.chat import ChatMessage
from ..models.commerce import Order, OrderItem
from ..models.site import Event, EventRegistration, ContactMessage, SupportTicket
from ..models.competition import ArtistKyc, Competition, CompetitionEntry
from ..models.enquiry import Enquiry
from ..models.review import Review, OwnedArtwork
from ..schemas.extra import AdminArtistIn, AdminArtistOut
from ..security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


def _artist_slug(user_id: uuid.UUID) -> str:
    # Same formula artworks.create_artwork uses, so a directly-added artist and
    # one who later logs in to submit work resolve to the SAME catalog Artist.
    return f"artist-{user_id.hex[:8]}"


@router.get("/stats")
def stats(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    count = lambda model, *w: db.scalar(select(func.count()).select_from(model).where(*w)) or 0
    return {
        "pending_orders": count(Order, Order.status == "pending"),
        "unread_messages": count(ChatMessage, ChatMessage.sender == "me"),
        "event_registrations": count(EventRegistration),
        "recent_artworks": count(Artwork, Artwork.created_at >= week_ago),
        "contact_messages": count(ContactMessage),
        "open_tickets": count(SupportTicket, SupportTicket.status == "open"),
        "pending_artists": count(ArtistKyc, ArtistKyc.status.in_(("pending", "unverified"))),
        "pending_artworks": count(Artwork, Artwork.status == "pending"),
    }


@router.get("/analytics")
def analytics(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Site-wide counts and distributions for the admin overview (numeric)."""
    count = lambda model, *w: db.scalar(select(func.count()).select_from(model).where(*w)) or 0

    def group(col):
        rows = db.execute(select(col, func.count()).group_by(col)).all()
        return {(str(k) if k not in (None, "") else "—"): v for k, v in rows}

    artworks_total = count(Artwork)
    customizable = count(Artwork, Artwork.customizable == True)  # noqa: E712
    return {
        "users": {"total": count(User), "by_role": group(Profile.role)},
        "artists": {
            "kyc_total": count(ArtistKyc),
            "verified": count(ArtistKyc, ArtistKyc.status == "verified"),
            "unverified": count(ArtistKyc, ArtistKyc.status.in_(("pending", "unverified"))),
        },
        "artworks": {
            "total": artworks_total, "customizable": customizable,
            "fixed": artworks_total - customizable,
            "featured": count(Artwork, Artwork.featured == True),  # noqa: E712
            "by_category": group(Artwork.category_id),
            "by_status": group(Artwork.status),
        },
        "orders": {"total": count(Order), "by_status": group(Order.status)},
        "enquiries": {"total": count(Enquiry), "by_status": group(Enquiry.status)},
        "events": {"total": count(Event), "registrations": count(EventRegistration)},
        "competitions": {"total": count(Competition), "entries": count(CompetitionEntry), "by_status": group(Competition.status)},
        "support": {
            "tickets": count(SupportTicket),
            "open_tickets": count(SupportTicket, SupportTicket.status == "open"),
            "contact_messages": count(ContactMessage),
        },
        "collection": {"owned": count(OwnedArtwork), "reviews": count(Review)},
    }


# Share of artwork revenue paid out to artists (COGS); the rest is platform margin.
ARTIST_PAYOUT_RATE = 0.60
PAID_STATUSES = {"paid", "shipped", "delivered"}


@router.get("/revenue")
def revenue(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Monthly profit & loss derived from paid orders.

    revenue = order totals collected; of which GST + delivery are pass-through.
    Net profit = platform margin on artwork sales (artwork sales − artist payouts).
    """
    orders = db.scalars(select(Order).order_by(Order.created_at)).all()
    months: dict[str, dict] = {}
    blank = lambda: {"orders": 0, "revenue": 0.0, "art_sales": 0.0, "gst": 0.0,
                     "delivery": 0.0, "logistics": 0.0, "payout": 0.0, "profit": 0.0}
    totals = blank()
    pending = 0
    for o in orders:
        if o.status not in PAID_STATUSES:
            if o.status == "pending":
                pending += 1
            continue
        key = o.created_at.strftime("%Y-%m")
        m = months.setdefault(key, blank())
        rev = float(o.total or 0)
        art = float(o.subtotal or 0)
        gst = float(o.tax or 0)
        delivery = float(o.delivery_fee or 0)
        logistics = rev - art - gst - delivery   # transport + setup collected
        payout = round(art * ARTIST_PAYOUT_RATE)
        profit = art - payout                    # platform margin on art
        for bucket in (m, totals):
            bucket["orders"] += 1
            bucket["revenue"] += rev
            bucket["art_sales"] += art
            bucket["gst"] += gst
            bucket["delivery"] += delivery
            bucket["logistics"] += logistics
            bucket["payout"] += payout
            bucket["profit"] += profit
    by_month = [{"month": k, **v} for k, v in sorted(months.items())]
    return {
        "payout_rate": ARTIST_PAYOUT_RATE,
        "pending_orders": pending,
        "totals": totals,
        "by_month": by_month,
    }


# ── Accounting export (CSV + Tally-importable XML) ───────────────────────────
def _paid_order_rows(db: Session) -> list[dict]:
    """One accounting row per *paid* order — the figures behind Price & Tally."""
    rows = []
    for o in db.scalars(select(Order).order_by(Order.created_at)).all():
        if o.status not in PAID_STATUSES:
            continue
        rev = float(o.total or 0); art = float(o.subtotal or 0)
        gst = float(o.tax or 0); delivery = float(o.delivery_fee or 0)
        logistics = round(rev - art - gst - delivery, 2)   # transport + setup
        payout = round(art * ARTIST_PAYOUT_RATE, 2)
        rows.append({
            "id": str(o.id), "date": o.created_at,
            "customer": o.full_name or o.email or "Customer",
            "status": o.status, "total": rev, "art": art, "gst": gst,
            "logistics": logistics, "delivery": delivery,
            "payout": payout, "profit": round(art - payout, 2),
        })
    return rows


def _tally_voucher(vtype: str, date: datetime, narration: str, entries: list[tuple]) -> str:
    """entries = [(ledger_name, is_debit, amount), …]. Tally signs debits negative."""
    d = date.strftime("%Y%m%d")
    legs = ""
    for name, is_debit, amount in entries:
        amt = -abs(amount) if is_debit else abs(amount)
        legs += (
            "<ALLLEDGERENTRIES.LIST>"
            f"<LEDGERNAME>{_xesc(name)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'Yes' if is_debit else 'No'}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{amt:.2f}</AMOUNT>"
            "</ALLLEDGERENTRIES.LIST>"
        )
    return (
        "<TALLYMESSAGE xmlns:UDF=\"TallyUDF\">"
        f"<VOUCHER VCHTYPE=\"{vtype}\" ACTION=\"Create\" OBJVIEW=\"Accounting Voucher View\">"
        f"<DATE>{d}</DATE><EFFECTIVEDATE>{d}</EFFECTIVEDATE>"
        f"<NARRATION>{_xesc(narration)}</NARRATION>"
        f"<VOUCHERTYPENAME>{vtype}</VOUCHERTYPENAME>"
        f"{legs}</VOUCHER></TALLYMESSAGE>"
    )


def _tally_xml(rows: list[dict]) -> str:
    msgs = []
    for r in rows:
        ref = r["id"][:8].upper()
        sales = [(r["customer"], True, r["total"]), ("Sales - Artwork", False, r["art"])]
        if r["gst"]:
            sales.append(("Output GST", False, r["gst"]))
        log_del = round(r["logistics"] + r["delivery"], 2)
        if log_del:
            sales.append(("Logistics & Delivery Income", False, log_del))
        msgs.append(_tally_voucher("Sales", r["date"], f"Art Coliseum Order #{ref} - {r['customer']}", sales))
        if r["payout"]:
            msgs.append(_tally_voucher("Journal", r["date"], f"Artist payout - order #{ref}",
                        [("Artist Payouts", True, r["payout"]), ("Artist Payable", False, r["payout"])]))
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>"
        "<BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC>"
        f"<REQUESTDATA>{''.join(msgs)}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
    )


@router.get("/revenue/export")
def export_revenue(format: str = Query("csv"), db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Download paid-order accounting data: `format=csv` (accountant ledger) or
    `format=tally` (Tally-importable vouchers XML)."""
    rows = _paid_order_rows(db)

    if format == "tally":
        return Response(
            content=_tally_xml(rows), media_type="application/xml",
            headers={"Content-Disposition": 'attachment; filename="art-coliseum-tally.xml"'},
        )

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Order ID", "Customer", "Status", "Gross Total", "Artwork Sales",
                "GST", "Logistics (Transport+Setup)", "Delivery", "Artist Payout (Expense)", "Net Profit"])
    tot = dict(total=0.0, art=0.0, gst=0.0, logistics=0.0, delivery=0.0, payout=0.0, profit=0.0)
    for r in rows:
        w.writerow([r["date"].strftime("%d-%m-%Y"), r["id"][:8].upper(), r["customer"], r["status"],
                    f'{r["total"]:.2f}', f'{r["art"]:.2f}', f'{r["gst"]:.2f}', f'{r["logistics"]:.2f}',
                    f'{r["delivery"]:.2f}', f'{r["payout"]:.2f}', f'{r["profit"]:.2f}'])
        for k in tot:
            tot[k] += r[k]
    w.writerow([])
    w.writerow(["TOTAL", "", "", f"{len(rows)} orders", f'{tot["total"]:.2f}', f'{tot["art"]:.2f}',
                f'{tot["gst"]:.2f}', f'{tot["logistics"]:.2f}', f'{tot["delivery"]:.2f}',
                f'{tot["payout"]:.2f}', f'{tot["profit"]:.2f}'])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="art-coliseum-revenue.csv"'},
    )


@router.get("/artists")
def list_artist_kyc(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(ArtistKyc).order_by(ArtistKyc.created_at.desc())).all()
    out = []
    for k in rows:
        u = db.get(User, k.user_id)
        out.append({
            "user_id": str(k.user_id), "name": k.name, "email": u.email if u else None,
            "age": k.age, "art_type": k.art_type, "location": k.location, "about": k.about,
            "avatar_url": k.avatar_url, "gender": k.gender,
            "status": k.status, "rejection_reason": k.rejection_reason,
            "role": (u.profile.role if u and u.profile else "user"),
        })
    return out


@router.post("/artists/create", response_model=AdminArtistOut, status_code=201)
def create_artist(body: AdminArtistIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Add an artist directly (bypassing the competition): creates a login
    account (verified artist) AND a catalog profile shown in the Artists listing.
    The admin can then add artworks on the artist's behalf."""
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=email, password_hash=hash_password(body.password))
    user.profile = Profile(
        full_name=body.name, role="artist", artist_status="verified",
        avatar_url=body.image_url,
    )
    db.add(user)
    db.flush()  # get user.id

    slug = _artist_slug(user.id)
    db.add(Artist(
        id=slug, name=body.name, role="Art Coliseum Artist", bio=body.bio,
        image_url=body.image_url, location=body.location, age=body.age, art_type=body.art_type,
        gender=body.gender,
    ))
    # Mirror into KYC (verified) so the artist shows in the admin artists list.
    db.add(ArtistKyc(
        user_id=user.id, name=body.name, age=body.age, art_type=body.art_type,
        location=body.location, about=body.bio, avatar_url=body.image_url,
        gender=body.gender, status="verified",
    ))
    db.commit()
    return AdminArtistOut(user_id=user.id, artist_id=slug, name=body.name, email=email)


@router.post("/jury/create", status_code=201)
def create_jury(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Create a jury login (role=jury) the admin hands to an external judge.
    Jury members rate competition entries on the day; they are not sellers."""
    email = (body.get("email") or "").lower().strip()
    password = body.get("password") or ""
    name = body.get("name") or ""
    if not email or not password or not name:
        raise HTTPException(status_code=400, detail="Email, password and name are required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(password))
    user.profile = Profile(full_name=name, role="jury", artist_status="none")
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": str(user.id), "email": email, "name": name}


@router.post("/artists/{user_id}/verify")
def verify_artist(user_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Approve an artist application → grant dashboard / selling access."""
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == user_id))
    if kyc:
        kyc.status = "verified"
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if prof:
        prof.artist_status = "verified"
        prof.role = "artist"
    db.commit()
    return {"ok": True}


@router.post("/artists/{user_id}/reject")
def reject_artist(user_id: uuid.UUID, body: dict | None = None, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Decline (or revoke) an artist application — sends them back to a plain user.
    An optional `reason` is stored and shown to the applicant so they can reapply."""
    reason = (body or {}).get("reason") or None
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == user_id))
    if kyc:
        kyc.status = "rejected"
        kyc.rejection_reason = reason
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if prof:
        prof.artist_status = "rejected"
        if prof.role == "artist":
            prof.role = "user"
    db.commit()
    return {"ok": True}


@router.delete("/artists/{user_id}")
def delete_artist(user_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Permanently remove an artist: deletes their artworks, catalog profile,
    KYC record and login account. A piece that is tied to an existing
    order/enquiry/review can't be hard-deleted (the DB references it) — those
    are taken offline instead so the removal never gets stuck. Order history is
    preserved (the order's user link is nulled, the rows are not removed)."""
    slug = _artist_slug(user_id)

    # 1. Remove their artworks. Delete where possible; for any piece referenced
    #    elsewhere, fall back to hiding it from the public site.
    deleted = hidden = 0
    works = db.scalars(select(Artwork).where(Artwork.artist_id == slug)).all()
    for art in works:
        try:
            with db.begin_nested():
                db.delete(art)
            deleted += 1
        except IntegrityError:
            art.status = "rejected"
            art.in_stock = False
            art.artist_id = None
            hidden += 1

    # 2. Drop the catalog Artist profile (removes them from the public listing).
    artist = db.get(Artist, slug)
    if artist:
        db.delete(artist)

    # 3. Remove the KYC record and the login account. Deleting the user cascades
    #    their profile, chat, cart and enquiries; orders keep a null user link.
    kyc = db.scalar(select(ArtistKyc).where(ArtistKyc.user_id == user_id))
    if kyc:
        db.delete(kyc)
    user = db.get(User, user_id)
    if user:
        db.delete(user)

    db.commit()
    return {"ok": True, "artworks_deleted": deleted, "artworks_hidden": hidden}


@router.patch("/profiles/{user_id}/role")
def set_role(user_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    role = body.get("role")
    if role not in {"user", "artist", "admin", "jury"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    prof = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    prof.role = role
    if role == "admin":
        prof.is_admin = True
    db.commit()
    return {"ok": True, "role": role}
