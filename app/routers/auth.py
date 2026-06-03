"""Authentication endpoints: register, login, refresh, logout, me."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models.user import User, Profile
from ..schemas.auth import (
    RegisterIn, LoginIn, RefreshIn, TokenOut, MeOut, UserOut,
)
from ..security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenOut:
    sub = str(user.id)
    prof = user.profile
    return TokenOut(
        access=create_access_token(sub),
        refresh=create_refresh_token(sub),
        user=UserOut(id=user.id, email=user.email),
        role=prof.role if prof else "user",
        artist_status=prof.artist_status if prof else "none",
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.email == body.email.lower()))
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    user.profile = Profile(full_name=body.full_name, phone=body.phone, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _token_response(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh, expected_type="refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        uid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    return _token_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: User = Depends(get_current_user)):
    # Stateless JWT — client discards tokens. Endpoint exists for symmetry.
    return None


@router.patch("/me", response_model=MeOut)
def update_me(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prof = user.profile
    if prof:
        if "full_name" in body and body["full_name"] is not None:
            prof.full_name = body["full_name"]
        if "phone" in body and body["phone"] is not None:
            prof.phone = body["phone"]
        if "avatar_url" in body and body["avatar_url"] is not None:
            prof.avatar_url = body["avatar_url"]
        db.commit()
        db.refresh(user)
    return MeOut(
        user=UserOut(id=user.id, email=user.email),
        role=prof.role if prof else "user",
        artist_status=prof.artist_status if prof else "none",
        full_name=prof.full_name if prof else None,
        phone=prof.phone if prof else None,
        avatar_url=prof.avatar_url if prof else None,
    )


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    prof = user.profile
    return MeOut(
        user=UserOut(id=user.id, email=user.email),
        role=prof.role if prof else "user",
        artist_status=prof.artist_status if prof else "none",
        full_name=prof.full_name if prof else None,
        phone=prof.phone if prof else None,
        avatar_url=prof.avatar_url if prof else None,
    )
