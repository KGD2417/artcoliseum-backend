"""Pydantic models for chat."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    conversation_key: str
    sender: str
    text: str
    created_at: datetime


class ChatMessageIn(BaseModel):
    conversation_key: str
    sender: str = "me"
    text: str
    target_user_id: uuid.UUID | None = None  # admin replying on behalf of a user


class ChatReadIn(BaseModel):
    conversation_key: str


class PeerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str | None = None
    avatar_url: str | None = None
