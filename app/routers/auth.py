"""Authentication endpoints: register, login, refresh, logout, me."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..ratelimit import limiter
from ..models.user import User, Profile
from ..schemas.auth import (
    RegisterIn, LoginIn, RefreshIn, TokenOut, MeOut, UserOut,
    ForgotPasswordIn, ResetPasswordIn, ChangePasswordIn,
)
from ..security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    create_reset_token, password_fingerprint,
)
from ..utils.email import send_email

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
@limiter.limit("20/minute")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status_code=409, detail="Email already registered")

    phone = (body.phone or "").strip() or None
    if phone and db.scalar(select(Profile).where(Profile.phone == phone)):
        raise HTTPException(status_code=409, detail="Phone number already registered")

    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    user.profile = Profile(full_name=body.full_name, phone=phone, role="user")
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent signup with the same email/phone.
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or phone number already registered")
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenOut)
@limiter.limit("20/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
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


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
def forgot_password(
    request: Request,
    body: ForgotPasswordIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user:
        token = create_reset_token(str(user.id), user.password_hash)
        link = f"{settings.FRONTEND_ORIGIN}/reset-password?token={token}"
        message = (
            "We received a request to reset your Art Coliseum password.\n\n"
            f"Use the link below to choose a new password (valid for {settings.RESET_TTL_MIN} minutes):\n\n"
            f"{link}\n\n"
            "If you didn't request this, you can safely ignore this email — your "
            "password won't change."
        )
        # No-op when SMTP isn't configured; log the link so dev can still test.
        if not send_email("Reset your Art Coliseum password", message, to=user.email):
            print(f"[auth] password reset link for {user.email}: {link}")
    # Always 202 — never reveal whether an account exists for this email.
    return {"detail": "If an account exists for that email, a reset link has been sent."}


@router.post("/reset-password", response_model=TokenOut)
@limiter.limit("10/minute")
def reset_password(request: Request, body: ResetPasswordIn, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    payload = decode_token(body.token, expected_type="reset")
    if not payload:
        raise invalid
    try:
        uid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise invalid
    user = db.get(User, uid)
    # The fingerprint binds the token to the password it was issued for, so a
    # link can't be replayed once it's been used (or the password changed).
    if not user or payload.get("pwf") != password_fingerprint(user.password_hash):
        raise invalid

    user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: User = Depends(get_current_user)):
    # Stateless JWT — client discards tokens. Endpoint exists for symmetry.
    return None


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return None


@router.patch("/me", response_model=MeOut)
def update_me(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    prof = user.profile
    if prof:
        if "full_name" in body and body["full_name"] is not None:
            prof.full_name = body["full_name"]
        if "phone" in body and body["phone"] is not None:
            phone = str(body["phone"]).strip() or None
            if phone and db.scalar(
                select(Profile).where(Profile.phone == phone, Profile.user_id != user.id)
            ):
                raise HTTPException(status_code=409, detail="Phone number already registered")
            prof.phone = phone
        if "avatar_url" in body and body["avatar_url"] is not None:
            prof.avatar_url = body["avatar_url"]
        if "addresses" in body and isinstance(body["addresses"], list):
            # Replace the saved address book; keep only well-formed dict entries.
            prof.addresses = [a for a in body["addresses"] if isinstance(a, dict)]
        db.commit()
        db.refresh(user)
    return _me_out(user, prof)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)):
    return _me_out(user, user.profile)


def _me_out(user: User, prof) -> MeOut:
    return MeOut(
        user=UserOut(id=user.id, email=user.email),
        role=prof.role if prof else "user",
        artist_status=prof.artist_status if prof else "none",
        full_name=prof.full_name if prof else None,
        phone=prof.phone if prof else None,
        avatar_url=prof.avatar_url if prof else None,
        addresses=(prof.addresses or []) if prof else [],
    )
