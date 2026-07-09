# amendia_auth/settings.py
"""Auth configuration, env-prefixed per consuming service.

Each service loads its own copy with ``load_auth_settings("<PREFIX>_")`` so the
env keys read as e.g. ``AGENTRT_AUTH_ISSUER``, ``REGISTRY_AUTH_AUDIENCE``. The
single-deployment model means exactly one issuer/audience — no allowlists.
"""
from __future__ import annotations

from typing import Set

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    # OIDC resource-server config (one issuer per deployment).
    issuer: str = ""
    audience: str = "amendia-api"
    jwks_ttl_seconds: int = 600
    leeway_seconds: int = 30

    # Dev-networking escape hatch: when set, JWKS is fetched from this URL directly
    # (discovery is skipped) while `iss` is still validated against `issuer`. This
    # is THE compose footgun: token `iss` is the browser-facing issuer
    # (http://localhost:8087/...), unreachable from inside the network, so services
    # fetch keys via the internal alias (http://keycloak:8080/.../certs) instead.
    jwks_uri: str = ""

    # Identity service (principal → Amendia user + roles).
    identity_base_url: str = "http://localhost:8086"
    resolve_cache_ttl_seconds: int = 30

    # Shared internal-token for service-to-service calls inside the deployment
    # boundary (X-Amendia-Internal). Same value across services + identity.
    # TODO(auth-hardening): replace the shared static token with mTLS / signed
    # service tokens (design doc §2.5).
    internal_token: str = ""

    # Tests / local hacking only — NEVER default-true in compose. When true,
    # dependencies yield a synthetic user with all seeded roles (loud warning).
    auth_disabled: bool = False

    # Synthetic user used when auth_disabled is true.
    dev_user_id: str = "usr-dev"
    dev_user_email: str = "dev@amendia.local"
    dev_user_name: str = "Dev User"
    dev_user_roles: str = (
        "role.payments.ops_analyst,role.payments.ops_approver,"
        "role.process.owner,role.platform.admin"
    )

    model_config = SettingsConfigDict(env_prefix="AUTH_", extra="ignore")

    @property
    def synthetic_roles(self) -> Set[str]:
        return {r.strip() for r in self.dev_user_roles.split(",") if r.strip()}


def load_auth_settings(service_prefix: str) -> AuthSettings:
    """Build an ``AuthSettings`` reading ``<service_prefix>AUTH_*`` env vars.

    e.g. ``load_auth_settings("AGENTRT_")`` reads ``AGENTRT_AUTH_ISSUER`` etc.
    """
    prefix = f"{service_prefix}AUTH_"

    class _ServiceAuthSettings(AuthSettings):
        model_config = SettingsConfigDict(env_prefix=prefix, extra="ignore")

    return _ServiceAuthSettings()  # type: ignore[call-arg]
