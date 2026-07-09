# app/deps.py
"""FastAPI dependency providers — repos/services live on app.state (set in lifespan)."""
from __future__ import annotations

from fastapi import Request

from app.dal.role_repo import RoleRepository
from app.dal.user_repo import UserRepository
from app.db.mongo import MongoClient
from app.services.resolver import ResolveService


def get_mongo(request: Request) -> MongoClient:
    return request.app.state.mongo


def get_user_repo(request: Request) -> UserRepository:
    return request.app.state.user_repo


def get_role_repo(request: Request) -> RoleRepository:
    return request.app.state.role_repo


def get_resolve_service(request: Request) -> ResolveService:
    return request.app.state.resolve_service
