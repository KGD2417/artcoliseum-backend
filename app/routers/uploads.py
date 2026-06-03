"""File uploads → local static storage (replaces Supabase Storage)."""
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..config import settings
from ..deps import get_current_user
from ..models.user import User

router = APIRouter(prefix="/uploads", tags=["uploads"])

# kind → (subdir, allowed extensions)
KINDS = {
    "image": ("images", {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}),
    "video": ("videos", {".mp4", ".webm", ".mov", ".m4v"}),
    "model": ("models", {".glb", ".gltf"}),
}

MAX_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("")
async def upload(
    file: UploadFile = File(...),
    kind: str = Form("image"),
    _: User = Depends(get_current_user),
):
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid kind: {kind}")
    subdir, allowed = KINDS[kind]

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Extension {ext} not allowed for {kind}")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    dest_dir = os.path.join(settings.UPLOAD_DIR, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(dest_dir, name), "wb") as f:
        f.write(data)

    return {"url": f"/uploads/{subdir}/{name}", "kind": kind}
