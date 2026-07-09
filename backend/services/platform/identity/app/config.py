# app/config.py
"""Service configuration (env prefix ``IDENTITY_``).

The identity service also consumes ``amendia_auth`` (for ``/me`` and the admin
guards), so it loads auth settings under the same ``IDENTITY_AUTH_*`` convention.
The internal resolve endpoint is guarded by the shared static token; we mirror
``IDENTITY_INTERNAL_TOKEN`` into the auth context so there is a single secret.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from amendia_auth import AuthSettings, load_auth_settings


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"

    # JIT provisioning: status new users are created with.
    JIT_DEFAULT_STATUS: str = "active"

    # Seeding (idempotent; role assignments keyed by email + JIT-attach on first login).
    SEED_ON_STARTUP: bool = False

    # Shared internal-token guarding POST /internal/resolve-principal. Same value
    # the enforcing services send as X-Amendia-Internal.
    # TODO(auth-hardening): replace with mTLS / signed service tokens.
    INTERNAL_TOKEN: str = ""

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8086
    LOG_LEVEL: str = "INFO"

    # Dev-only permissive CORS (mirrors the other services).
    ENABLE_DEV_CORS: bool = True

    model_config = SettingsConfigDict(
        env_prefix="IDENTITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]

# Auth config for /me + admin guards (IDENTITY_AUTH_ISSUER, _AUDIENCE, ...).
auth_settings: AuthSettings = load_auth_settings("IDENTITY_")
# One source of truth for the internal secret: IDENTITY_INTERNAL_TOKEN drives the
# resolve-endpoint guard whether or not IDENTITY_AUTH_INTERNAL_TOKEN was also set.
if settings.INTERNAL_TOKEN:
    auth_settings.internal_token = settings.INTERNAL_TOKEN
