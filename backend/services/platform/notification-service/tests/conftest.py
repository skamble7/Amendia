"""Test wiring: build the app and set app.state manually (ASGITransport does not run
lifespan), so tests never need a live RabbitMQ. A real AuthContext is attached so the
unauthenticated 401 path is exercised; the streaming test overrides current_principal."""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from amendia_auth import AuthContext
from amendia_auth.settings import AuthSettings

from app.hub import NotificationHub
from app.main import create_app


class _FakeConsumer:
    is_ready = True

    async def stop(self) -> None:  # pragma: no cover - not used in tests
        pass


@pytest_asyncio.fixture
async def client():
    app = create_app()
    hub = NotificationHub()
    app.state.hub = hub
    app.state.consumer = _FakeConsumer()
    # Non-disabled auth with placeholder issuer/audience/jwks so AuthContext builds
    # without network calls; the no-token path 401s before any validation happens.
    app.state.auth = AuthContext(
        AuthSettings(
            issuer="http://keycloak/realms/amendia-dev",
            audience="amendia-api",
            jwks_uri="http://keycloak/certs",
            auth_disabled=False,
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, hub, app
