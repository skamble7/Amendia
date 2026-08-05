# app/deps.py
"""FastAPI providers reading the objects lifespan stashed on ``app.state``."""
from __future__ import annotations

from fastapi import Request

from app.clickhouse.reader import AuditReader
from app.events.consumer import AuditConsumer


def get_reader(request: Request) -> AuditReader:
    return request.app.state.reader


def get_consumer(request: Request) -> AuditConsumer:
    return request.app.state.consumer


def get_sealer(request: Request):
    return request.app.state.sealer
