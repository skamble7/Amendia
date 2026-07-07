# app/deps.py
"""FastAPI dependency providers.

The repository, mongo client, and consumer live on ``app.state`` (populated by
the lifespan). Routes depend on these so tests can override them with fakes.
"""
from __future__ import annotations

from fastapi import Request

from app.dal.ingestion_repo import IngestionRepository
from app.db.mongo import MongoClient
from app.events.rabbit import RabbitConsumer


def get_repo(request: Request) -> IngestionRepository:
    return request.app.state.repo


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo


def get_consumer(request: Request) -> RabbitConsumer:
    return request.app.state.consumer
