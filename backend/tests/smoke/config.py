# backend/tests/smoke/config.py
"""Endpoint + auth configuration for the corpus smoke suite.

Every value is read from the environment with **compose host-port defaults** (see
``backend/deploy/docker-compose.yml`` — services are published on ``18xxx``; Keycloak on ``8087``;
``pega-stub`` on ``9095`` from its own compose). Override any of them to point the suite at a different
deployment. No secrets beyond the well-known dev CLI client (mirrors ``tools/demo_wire_repair.sh``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v or default


@dataclass(frozen=True)
class SmokeConfig:
    ingestor: str
    runtime: str
    registry: str
    glea: str
    pega_stub: str
    stub: str
    notification: str
    identity: str
    keycloak: str
    realm: str
    cli_client: str
    cli_secret: str
    dev_password: str

    @property
    def token_url(self) -> str:
        return f"{self.keycloak}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def oidc_config_url(self) -> str:
        return f"{self.keycloak}/realms/{self.realm}/.well-known/openid-configuration"

    # Core services that must be reachable for the suite to run at all (a driver-specific service like
    # pega-stub/glea is checked per-scenario, so a missing one skips only that domain).
    def core_health(self) -> dict[str, str]:
        return {
            "ingestor": f"{self.ingestor}/health",
            "agent-runtime": f"{self.runtime}/health",
            "process-registry": f"{self.registry}/health",
            "stub-trigger-generator": f"{self.stub}/health",
            "keycloak": self.oidc_config_url,
        }


def load_config() -> SmokeConfig:
    return SmokeConfig(
        ingestor=_env("INGESTOR", "http://localhost:18082"),
        runtime=_env("RUNTIME", "http://localhost:18083"),
        registry=_env("REGISTRY", "http://localhost:18084"),
        glea=_env("GLEA", "http://localhost:18090"),
        pega_stub=_env("PEGA_STUB", "http://localhost:9095"),
        stub=_env("STUB", "http://localhost:18081"),
        notification=_env("NOTIFICATION", "http://localhost:18088"),
        identity=_env("IDENTITY", "http://localhost:18086"),
        keycloak=_env("KEYCLOAK", "http://localhost:8087"),
        realm=_env("REALM", "amendia-dev"),
        cli_client=_env("CLI_CLIENT", "amendia-dev-cli"),
        cli_secret=_env("CLI_SECRET", "dev-cli-secret"),
        dev_password=_env("DEV_PASSWORD", "dev-password"),
    )
