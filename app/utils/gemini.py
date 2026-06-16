"""Gemini image generation for the AR Room Visualizer (desktop / no-AR path).

Uses Gemini's image model ("Nano Banana") to composite an artwork into a photo
of the user's room, producing a photorealistic preview. This runs server-side so
the *billing* API key never reaches the browser.

Set GEMINI_API_KEY to enable. httpx is imported lazily so the app boots without
the key. See INTEGRATIONS.md.
"""
from __future__ import annotations

import base64

from ..config import settings

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# How each artwork type should sit in the room.
_PLACEMENT = {
    "painting": "hung flat and framed on a suitable wall at eye level",
    "mural": "painted as a large mural covering most of one wall",
    "wallpaper": "applied as wallpaper covering an entire wall",
    "sculpture": "placed on the floor as a free-standing sculpture",
}


def is_enabled() -> bool:
    """True when a Gemini billing key is configured."""
    return bool(settings.GEMINI_API_KEY)


def _split_data_url(data_url: str) -> tuple[str, str]:
    """'data:image/png;base64,XXXX' -> ('image/png', 'XXXX')."""
    header, b64 = data_url.split(",", 1)
    mime = header[5:].split(";")[0] or "image/png"
    return mime, b64


def _to_inline(src: str) -> tuple[str, str]:
    """Resolve an image reference to (mime_type, base64). Accepts a data: URL, an
    http(s) URL (fetched server-side, avoiding browser CORS/canvas issues), or
    raw base64."""
    s = (src or "").strip()
    if s.startswith("data:"):
        return _split_data_url(s)
    if s.startswith("http://") or s.startswith("https://"):
        import httpx
        r = httpx.get(s, timeout=30, follow_redirects=True)
        r.raise_for_status()
        mime = (r.headers.get("content-type") or "image/png").split(";")[0]
        return mime, base64.b64encode(r.content).decode()
    return "image/png", s  # assume raw base64


def generate_room_visualization(room: str, artwork: str, art_type: str = "painting", prompt: str = "") -> str:
    """Return a data: URL of the room photo with the artwork composited in.

    Raises RuntimeError with a human-readable message on any failure (caller maps
    it to an HTTP error).
    """
    if not is_enabled():
        raise RuntimeError("Image generation is not configured")

    room_mime, room_b64 = _to_inline(room)
    art_mime, art_b64 = _to_inline(artwork)
    placement = _PLACEMENT.get(art_type, _PLACEMENT["painting"])

    instruction = (
        "You are a photorealistic interior-visualization tool. "
        "Image 1 is a photo of a real room. Image 2 is an artwork. "
        f"Produce a single photorealistic image of the SAME room with the artwork {placement}. "
        + (f"Placement request from the user: {prompt.strip()}. " if (prompt or "").strip() else "")
        + "Preserve the room's exact perspective, lighting, colours and proportions. "
        "Add realistic shadows and subtle reflections so the piece sits naturally in the space. "
        "Keep the artwork's content and colours faithful to Image 2. "
        "Return only the edited room image."
    )

    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": room_mime, "data": room_b64}},
                {"inline_data": {"mime_type": art_mime, "data": art_b64}},
            ],
        }],
    }

    import httpx
    url = _ENDPOINT.format(model=settings.GEMINI_IMAGE_MODEL)
    try:
        r = httpx.post(url, params={"key": settings.GEMINI_API_KEY}, json=body, timeout=120)
    except Exception as exc:  # pragma: no cover - network errors
        raise RuntimeError(f"Could not reach Gemini: {exc}")

    data = r.json() if r.content else {}
    if r.status_code >= 400:
        msg = ((data.get("error") or {}).get("message")) or f"{r.status_code} {r.reason_phrase}"
        raise RuntimeError(msg)

    # The REST API returns camelCase inlineData; accept snake_case too.
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    for p in parts:
        inline = p.get("inlineData") or p.get("inline_data")
        if inline and inline.get("data"):
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            return f"data:{mime};base64,{inline['data']}"

    # No image came back — surface any text (often a safety refusal reason).
    text = next((p.get("text") for p in parts if p.get("text")), None)
    raise RuntimeError(text or "Gemini returned no image")
