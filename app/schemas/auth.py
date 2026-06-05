"""Pydantic request/response models for auth."""
import uuid
from pydantic import BaseModel, EmailStr


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    phone: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr


class MeOut(BaseModel):
    user: UserOut
    role: str
    artist_status: str
    full_name: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    addresses: list | None = None


class TokenOut(BaseModel):
    access: str
    refresh: str
    user: UserOut
    role: str
    artist_status: str
