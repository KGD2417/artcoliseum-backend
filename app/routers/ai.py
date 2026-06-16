"""AI features — Gemini Room Visualizer for the AR viewer (desktop / no-AR path).

Generation runs server-side so the billing key stays secret. Requires a signed-in
user to limit abuse of the paid key.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_current_user
from ..models.user import User
from ..utils import gemini

router = APIRouter(prefix="/ai", tags=["ai"])


class VisualizeIn(BaseModel):
    room: str                      # data: URL (or base64) of the room photo
    artwork: str                   # data: URL, http(s) URL, or base64 of the artwork
    art_type: str = "painting"     # painting | mural | wallpaper | sculpture
    prompt: str = ""               # optional placement guidance


@router.get("/status")
def ai_status():
    """Lets the frontend know whether the photoreal generator is available."""
    return {"image_gen": gemini.is_enabled()}


@router.post("/visualize")
def visualize(body: VisualizeIn, me: User = Depends(get_current_user)):
    """Composite the artwork into the room photo and return a data: URL image."""
    if not gemini.is_enabled():
        raise HTTPException(status_code=503, detail="Image generation is not configured")
    try:
        image = gemini.generate_room_visualization(body.room, body.artwork, body.art_type, body.prompt)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"image": image}
