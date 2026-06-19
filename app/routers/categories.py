"""Public category listing + artist subtype creation + admin category management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_role
from ..models.user import User
from ..models.catalog import Category
from ..schemas.catalog import CategoryOut
from ..schemas.extra import CategoryIn, CategoryUpdate, SubtypeIn

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return list(db.scalars(select(Category).order_by(Category.label)).all())


@router.post("", response_model=CategoryOut, status_code=201)
def create_main_category(
    body: CategoryIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Admin-only: create a new main medium (top-level category) with its page content."""
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="label is required")
    cid = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")
    if db.get(Category, cid):
        raise HTTPException(status_code=409, detail="Category already exists")
    cat = Category(
        id=cid, label=label, parent_id=None, kind="main",
        image_url=body.image_url, tagline=body.tagline, description=body.description,
        tabs=[t.model_dump() for t in body.tabs], pioneers=body.pioneers,
    )
    db.add(cat)
    db.commit()
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: str,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Admin-only: update a category's label or page content."""
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(cat, key, value)
    db.commit()
    db.refresh(cat)
    return cat


@router.post("/subtype", response_model=CategoryOut, status_code=201)
def create_subtype(body: SubtypeIn, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Verified artists/admins may add a new SUBTYPE (style) under an existing main medium."""
    role = me.profile.role if me.profile else "user"
    verified = me.profile and me.profile.artist_status == "verified"
    if role != "admin" and not verified:
        raise HTTPException(status_code=403, detail="Only verified artists may add styles")
    parent = db.get(Category, body.parent_id)
    if not parent or parent.kind != "main":
        raise HTTPException(status_code=400, detail="parent_id must be an existing main medium")
    slug = "".join(c if c.isalnum() else "-" for c in body.label.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="Enter a valid style name")
    # Scope the id to the parent medium so the same style name can live under
    # different mediums (e.g. "Black & White" under both Chinoiserie and Sketch).
    cid = f"{parent.id}-{slug}"
    existing = db.get(Category, cid)
    if existing:
        # Same style already exists under THIS medium — return it so the UI can
        # just select it, instead of erroring out.
        return existing
    cat = Category(
        id=cid, label=body.label.strip(), parent_id=body.parent_id, kind="subtype",
        image_url=body.image_url, description=body.description,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    """Admin-only: delete a category (and its subtypes cascade via FK if configured, else block)."""
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    # Prevent deleting a main category that still has subtypes
    if cat.kind == "main":
        subtypes = db.scalars(select(Category).where(Category.parent_id == category_id)).all()
        if subtypes:
            raise HTTPException(
                status_code=400,
                detail=f"Remove the {len(subtypes)} subtype(s) under this category first",
            )
    db.delete(cat)
    db.commit()
    return None
