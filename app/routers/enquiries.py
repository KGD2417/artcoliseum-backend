"""Enquiry → price reveal → approve gate."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.catalog import Artwork
from ..models.enquiry import Enquiry, BuyApproval
from ..models.chat import ChatMessage
from ..schemas.commerce import EnquiryCreateIn, RevealPriceIn, EnquiryOut, GateOut
from ..schemas.chat import ChatMessageOut
from ..utils.pricing import compute_custom_price
from ..websocket import manager

router = APIRouter(prefix="/enquiries", tags=["enquiries"])


def _conv_key(artwork_id: str) -> str:
    return f"enquiry:{artwork_id}"


async def _post_system_message(db: Session, user_id: uuid.UUID, key: str, text: str):
    """Insert a curator chat message into the user's thread and broadcast it."""
    msg = ChatMessage(user_id=user_id, conversation_key=key, sender="curator", text=text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    out = ChatMessageOut.model_validate(msg).model_dump()
    await manager.broadcast(out, {str(user_id)}, notify_admins=True)


@router.post("", response_model=EnquiryOut, status_code=201)
async def create_enquiry(body: EnquiryCreateIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    art = db.get(Artwork, body.artwork_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artwork not found")
    key = _conv_key(body.artwork_id)
    selection = {
        "options": body.options or {},
        "custom_width": body.custom_width,
        "custom_height": body.custom_height,
        "custom_unit": body.custom_unit,
    }

    # Auto-compute the price from the artwork's own pricing + the buyer's choices.
    price = compute_custom_price(
        art,
        options=body.options,
        custom_width=body.custom_width,
        custom_height=body.custom_height,
        custom_unit=body.custom_unit,
    )

    # Reuse an existing live enquiry for this user+artwork; refresh its quote.
    enq = db.scalar(
        select(Enquiry).where(
            Enquiry.user_id == me.id,
            Enquiry.artwork_id == body.artwork_id,
            Enquiry.status.notin_(["rejected", "closed"]),
        )
    )
    if enq is None:
        enq = Enquiry(user_id=me.id, artwork_id=body.artwork_id, conversation_key=key, status="open")
        db.add(enq)

    enq.selection = selection
    # Don't downgrade an already-approved enquiry; otherwise quote the new price.
    if enq.status != "approved":
        enq.revealed_price = price
        enq.chosen_size_id = body.size_id
        enq.status = "price_revealed"
    db.commit()
    db.refresh(enq)

    # Auto-reveal: post the computed quote to the buyer's chat thread.
    if enq.status == "price_revealed":
        await _post_system_message(
            db, enq.user_id, key,
            f"Based on your selections, the price for this piece is ₹{price:,.0f}. "
            f"Our team will confirm shortly and unlock checkout.",
        )
    return enq


@router.get("/mine", response_model=list[EnquiryOut])
def my_enquiries(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return list(db.scalars(select(Enquiry).where(Enquiry.user_id == me.id).order_by(Enquiry.created_at.desc())).all())


def _enrich(enq: Enquiry, db: Session) -> dict:
    """EnquiryOut + the customer name and artwork title for the admin workspace."""
    out = EnquiryOut.model_validate(enq).model_dump()
    art = db.get(Artwork, enq.artwork_id)
    user = db.get(User, enq.user_id)
    out["artwork_title"] = art.title if art else enq.artwork_id
    out["customer_name"] = (
        (user.profile.full_name if user and user.profile and user.profile.full_name else None)
        or (user.email if user else None)
    )
    return out


@router.get("", response_model=list[EnquiryOut])
def all_enquiries(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.scalars(select(Enquiry).order_by(Enquiry.created_at.desc())).all()
    return [_enrich(e, db) for e in rows]


@router.get("/gate/{artwork_id}", response_model=GateOut)
def gate(artwork_id: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    # Predefined (non-customizable) artworks have a fixed price → buyable directly,
    # no enquiry/approval needed. Customizable artworks stay gated behind the
    # enquiry → admin price-reveal → approve flow.
    art = db.get(Artwork, artwork_id)
    if art and not art.customizable:
        return GateOut(state="bring_home", final_price=float(art.price or 0))

    appr = db.scalar(
        select(BuyApproval).where(
            BuyApproval.user_id == me.id,
            BuyApproval.artwork_id == artwork_id,
            BuyApproval.consumed == False,  # noqa: E712
        )
    )
    if appr:
        return GateOut(state="bring_home", approval_id=appr.id, final_price=float(appr.final_price))

    # Not yet approved — surface the latest auto-computed quote (if any) so the
    # buyer can see their price while the team confirms.
    enq = db.scalar(
        select(Enquiry).where(
            Enquiry.user_id == me.id,
            Enquiry.artwork_id == artwork_id,
            Enquiry.status.notin_(["rejected", "closed"]),
        ).order_by(Enquiry.created_at.desc())
    )
    quoted = float(enq.revealed_price) if enq and enq.revealed_price is not None else None
    return GateOut(state="enquire", quoted_price=quoted, enquiry_status=(enq.status if enq else None))


@router.post("/{enquiry_id}/reveal-price", response_model=EnquiryOut)
async def reveal_price(enquiry_id: uuid.UUID, body: RevealPriceIn, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    enq = db.get(Enquiry, enquiry_id)
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    enq.revealed_price = body.price
    enq.chosen_size_id = body.size_id
    enq.status = "price_revealed"
    db.commit()
    db.refresh(enq)
    await _post_system_message(
        db, enq.user_id, enq.conversation_key,
        f"The price for this piece is ₹{body.price:,.0f}. Let us know if you'd like to proceed.",
    )
    return enq


@router.post("/{enquiry_id}/approve", response_model=EnquiryOut)
async def approve(enquiry_id: uuid.UUID, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    enq = db.get(Enquiry, enquiry_id)
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    price = float(enq.revealed_price or 0)
    # Avoid duplicate active approvals.
    existing = db.scalar(
        select(BuyApproval).where(
            BuyApproval.user_id == enq.user_id,
            BuyApproval.artwork_id == enq.artwork_id,
            BuyApproval.consumed == False,  # noqa: E712
        )
    )
    if not existing:
        db.add(BuyApproval(
            user_id=enq.user_id, artwork_id=enq.artwork_id, enquiry_id=enq.id,
            approved_by=admin.id, final_price=price,
        ))
    enq.status = "approved"
    db.commit()
    db.refresh(enq)
    await _post_system_message(
        db, enq.user_id, enq.conversation_key,
        "Great news — you're approved to bring this piece home. The 'Bring it Home' button is now unlocked.",
    )
    return enq


@router.post("/{enquiry_id}/reject", response_model=EnquiryOut)
def reject(enquiry_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    enq = db.get(Enquiry, enquiry_id)
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    enq.status = "rejected"
    db.commit()
    db.refresh(enq)
    return enq
