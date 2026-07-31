# app/config.py
"""Service configuration (env prefix ``REGISTRY_``)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from amendia_bpmn import normalize_profile

from amendia_auth import AuthSettings, load_auth_settings

# L2: no hardcoded default seed. Seeding is opt-in (env-driven): with SEED_DIR unset the service boots
# clean and seeds nothing. A concrete seed path (e.g. an example pack) belongs in a dev compose / test
# config — never a code default that assumes one particular process.


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"

    # Seeding (drives the seed dataset through the real onboarding APIs). Unset by default → no seed.
    SEED_DIR: str = ""
    SEED_ON_STARTUP: bool = False
    # ADR-052: seed the reference wire-repair-standard pack (+ its art.payment.*/art.compliance.* schemas and
    # cap.payment.* capabilities) on startup. Default True keeps existing behavior/tests; set false once processes
    # are onboarded via the copilot, so the reference pack's domain baggage doesn't compete on triage.
    SEED_REFERENCE_PACK: bool = False

    # /resolve active-pack cache TTL (seconds)
    RESOLVE_CACHE_TTL: float = 30.0

    # Which BPMN conformance level may be activated (ADR-034 / Phase 2.8). "common_executable"
    # (DEFAULT) accepts the full built construct set; "common_subset" gates everything beyond the
    # Phase-0/1 base subset out. Derived required_profile is pinned at activation; the runtime's
    # AGENTRT_EXECUTION_PROFILE must be ≥ this for an activated pack to load. A retired granular env
    # value normalizes to common_executable.
    EXECUTION_PROFILE: Literal["common_subset", "common_executable"] = "common_executable"

    @field_validator("EXECUTION_PROFILE", mode="before")
    @classmethod
    def _normalize_profile(cls, v):
        return normalize_profile(v) if isinstance(v, str) else v

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8084
    LOG_LEVEL: str = "INFO"

    # Dev-only permissive CORS so a separately-served webui can call this
    # service directly. The Vite/nginx proxy avoids CORS in the normal setup;
    # this is default-on in compose and should be disabled in production.
    ENABLE_DEV_CORS: bool = True

    # ADR-052 Phase 2 — the onboarding copilot's LLM (reuses the polyllm + ConfigForge stack,
    # exactly like agent-runtime's llm/deep_agent capabilities; ADR-016/017/018). The copilot resolves
    # a ModelProfile by REF from config-forge — secrets stay references, never raw keys in code/config.
    CONFIG_FORGE_URL: str = "http://localhost:8040"
    # The strong model the copilot's semantic reasoning runs on. Mirrors agent-runtime's LLM_CONFIG_REF;
    # default to the same seeded Bedrock/Claude ref the runtime defaults to. A generate request may override.
    COPILOT_LLM_CONFIG_REF: str = "dev.llm.bedrock.explicit-creds"
    # Dev flag: when true the copilot never contacts ConfigForge/a live model — the generate endpoint
    # requires an injected/fake client. Tests set this (or monkeypatch the client seam) to run offline.
    COPILOT_LLM_DISABLED: bool = False

    model_config = SettingsConfigDict(
        env_prefix="REGISTRY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]

# Auth config (REGISTRY_AUTH_ISSUER, _AUDIENCE, _JWKS_URI, _IDENTITY_BASE_URL,
# _INTERNAL_TOKEN, ...).
auth_settings: AuthSettings = load_auth_settings("REGISTRY_")
