import asyncio
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, app_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.setdefault(app_id, set()).add(ws)

    async def disconnect(self, app_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(app_id)
            if conns is None:
                return
            conns.discard(ws)
            if not conns:
                self._conns.pop(app_id, None)

    async def broadcast(self, app_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._conns.get(app_id, set()))
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                conns = self._conns.get(app_id, set())
                for ws in dead:
                    conns.discard(ws)


manager = ConnectionManager()
