"""Collector testimonials — public read (published only), admin CRUD."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..models.user import User
from ..models.site import Testimonial
from ..schemas.extra import TestimonialOut

router = APIRouter(prefix="/testimonials", tags=["testimonials"])

# Editable fields accepted from the admin form.
_FIELDS = ("name", "designation", "quote", "image_url", "tag", "published", "sort_order")


def _ordered(query):
    return query.order_by(Testimonial.sort_order, Testimonial.created_at)


@router.get("", response_model=list[TestimonialOut])
def list_testimonials(db: Session = Depends(get_db)):
    """Public: only published testimonials, in display order."""
    rows = db.scalars(
        _ordered(select(Testimonial).where(Testimonial.published.is_(True)))
    ).all()
    return rows


@router.get("/all", response_model=list[TestimonialOut])
def list_all(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    """Admin: every testimonial, including unpublished ones."""
    return db.scalars(_ordered(select(Testimonial))).all()


@router.post("", response_model=TestimonialOut, status_code=201)
def create_testimonial(body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    if not body.get("name") or not body.get("quote"):
        raise HTTPException(status_code=422, detail="Name and quote are required")
    t = Testimonial(
        name=body["name"],
        designation=body.get("designation"),
        quote=body["quote"],
        image_url=body.get("image_url"),
        tag=body.get("tag"),
        published=bool(body.get("published", True)),
        sort_order=int(body.get("sort_order") or 0),
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.patch("/{testimonial_id}", response_model=TestimonialOut)
def update_testimonial(testimonial_id: uuid.UUID, body: dict, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    t = db.get(Testimonial, testimonial_id)
    if not t:
        raise HTTPException(status_code=404, detail="Testimonial not found")
    for f in _FIELDS:
        if f in body:
            setattr(t, f, body[f])
    db.commit(); db.refresh(t)
    return t


@router.delete("/{testimonial_id}", status_code=204)
def delete_testimonial(testimonial_id: uuid.UUID, db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    t = db.get(Testimonial, testimonial_id)
    if t:
        db.delete(t); db.commit()
    return None
