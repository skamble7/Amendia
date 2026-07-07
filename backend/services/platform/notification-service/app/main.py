# app/main.py
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.websocket_manager import websocket_manager
from app.rabbit_consumer import start_rabbit_consumer, stop_rabbit_consumer
from app.settings import settings
from app.logger import logger

app = FastAPI(title=settings.SERVICE_NAME, version="1.0.0")

# CORS (tighten in prod if your VS Code webview has a known origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.WS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rabbit_task: Optional[asyncio.Task] = None


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME, "env": settings.ENV}


@app.websocket(settings.WS_PATH)
async def ws_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for the frontend (VS Code webview).
    Clients receive enriched JSON events consumed from RabbitMQ.
    """
    await websocket_manager.connect(websocket)
    logger.info("WebSocket client connected")
    try:
        # Keep-alive loop; we don't expect messages from client, but this keeps the socket open
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await websocket_manager.disconnect(websocket)


@app.on_event("startup")
async def on_startup():
    global _rabbit_task
    logger.info("Starting Notification Service...")
    _rabbit_task = asyncio.create_task(start_rabbit_consumer())
    logger.info("Rabbit consumer task started")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down Notification Service...")
    await stop_rabbit_consumer()
    logger.info("Shutdown complete")
