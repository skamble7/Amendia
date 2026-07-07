# app/deps.py
"""FastAPI dependency providers.

The repository and publisher live on ``app.state`` (populated by the lifespan).
Routes depend on these providers so tests can override them with fakes via
``app.dependency_overrides`` — no live Mongo/Rabbit needed.
"""
from __future__ import annotations

from fastapi import Request

from app.dal.exceptions_repo import ExceptionRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitPublisher


def get_repo(request: Request) -> ExceptionRepository:
    return request.app.state.repo


def get_publisher(request: Request) -> RabbitPublisher:
    return request.app.state.publisher


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo
