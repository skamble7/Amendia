# app/websocket_manager.py
import asyncio
import json
from typing import Set, Union
from fastapi import WebSocket
from app.logger import logger  # expects module-level `logger` instance

class WebSocketManager:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        logger.info("WebSocket connected; total=%d", len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        logger.info("WebSocket disconnected; total=%d", len(self._clients))

    async def broadcast(self, message: Union[str, dict, list]) -> None:
        # normalize to text
        if not isinstance(message, str):
            message = json.dumps(message, separators=(",", ":"))

        async with self._lock:
            clients = list(self._clients)

        if not clients:
            return

        stale: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)

        if stale:
            async with self._lock:
                for ws in stale:
                    self._clients.discard(ws)
            logger.info("Pruned %d stale WebSocket(s); total=%d", len(stale), len(self._clients))

websocket_manager = WebSocketManager()
__all__ = ["WebSocketManager", "websocket_manager"]
