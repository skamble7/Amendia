# app/deps.py
"""FastAPI dependency providers — resources live on app.state (set in lifespan)."""
from __future__ import annotations

from fastapi import Request

from app.events.consumer import BroadcastConsumer
from app.hub import NotificationHub


def get_hub(request: Request) -> NotificationHub:
    return request.app.state.hub


def get_consumer(request: Request) -> BroadcastConsumer:
    return request.app.state.consumer
