"""WebSocket connection manager for live chat.

A single hub keeps every open socket tagged with its user_id + is_admin flag.
When a message is created, the chat router calls `manager.broadcast(...)` with the
set of recipient user_ids; admins always receive every message.
"""
import json


class ConnectionManager:
    def __init__(self):
        self.active: list[dict] = []  # [{ws, user_id, is_admin}]

    async def connect(self, ws, user_id: str, is_admin: bool):
        await ws.accept()
        self.active.append({"ws": ws, "user_id": user_id, "is_admin": is_admin})

    def disconnect(self, ws):
        self.active = [c for c in self.active if c["ws"] is not ws]

    async def broadcast(self, message: dict, recipient_ids: set[str], notify_admins: bool = True):
        payload = json.dumps(message, default=str)
        dead = []
        for c in self.active:
            if c["user_id"] in recipient_ids or (notify_admins and c["is_admin"]):
                try:
                    await c["ws"].send_text(payload)
                except Exception:
                    dead.append(c["ws"])
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
