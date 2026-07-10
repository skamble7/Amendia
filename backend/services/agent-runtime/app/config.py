# app/config.py
"""Service configuration (env prefix ``AGENTRT_``)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from amendia_auth import AuthSettings, load_auth_settings

# Default seed directory: <service-root>/seed/wire-repair-standard
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SEED_DIR = str(_SERVICE_ROOT / "seed" / "wire-repair-standard")


class Settings(BaseSettings):
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "amendia"
    # LangGraph checkpointer collections (runtime-private, same db).
    CHECKPOINT_COLLECTION: str = "lg_checkpoints"
    CHECKPOINT_WRITES_COLLECTION: str = "lg_checkpoint_writes"

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    RABBITMQ_DISPATCH_QUEUE: str = "agent-runtime.exception_dispatched.v1"

    # Process registry — pack/capability/schema/resolution API.
    REGISTRY_BASE_URL: str = "http://localhost:8084"
    # Envelope fetch + registry HTTP timeout (seconds).
    HTTP_TIMEOUT: int = 15
    # This service's own base URL (used in HITL task context_url).
    SELF_BASE_URL: str = "http://localhost:8083"

    # Capability execution: simulation seam (no external LLM/MCP calls).
    SIMULATION_MODE: bool = True

    # Execution substrate (ADR-017). Orthogonal to SIMULATION_MODE and LLM_CONFIG_REF:
    #   EXECUTION_MODE  chooses *where* a capability runs (in-process vs OpenShell sandbox);
    #   SIMULATION_MODE chooses *whether it's real*;
    #   LLM_CONFIG_REF  chooses *which model*.
    # ``native`` (default) is byte-for-byte today's in-process executor. ``nemoclaw`` routes
    # ``llm``/``mcp`` capability execution through NemoClaw's OpenShell sandbox (Phase 1).
    EXECUTION_MODE: Literal["native", "nemoclaw"] = "native"
    # OpenShell gateway endpoint (sandbox dispatch, secret brokering, OTLP). When unset in
    # ``nemoclaw`` mode a deterministic in-process fake client is used, so the sandboxed path
    # is exercisable in dev/CI with no live gateway.
    OPENSHELL_URL: Optional[str] = None
    # Fail-closed posture: in ``nemoclaw`` mode, if the gateway is unreachable at startup,
    # ``true`` refuses to start (a payments platform must not silently run capabilities
    # unsandboxed); ``false`` degrades to ``native`` with a loud warning (dev only).
    NEMOCLAW_REQUIRED: bool = False
    # Warm-sandbox pool size (used by the real HttpOpenShellClient; a scaffold in Phase 1).
    SANDBOX_POOL_SIZE: int = 4

    # Real LLM path (polyllm + ConfigForge). Used only when SIMULATION_MODE=false.
    # polyllm's RemoteConfigLoader fetches the model profile from ConfigForge by
    # canonical ref, so switching provider/model/keys is a config change (a ConfigForge
    # entry), never a code change. LLM_CONFIG_REF picks which seeded profile to use.
    CONFIG_FORGE_URL: str = "http://localhost:8040"
    LLM_CONFIG_REF: str = "dev.llm.bedrock.explicit-creds"

    # Debug/dev surfaces (guarded like the seed API).
    ENABLE_DEBUG_API: bool = True

    # Seeding
    SEED_DIR: str = _DEFAULT_SEED_DIR
    ENABLE_SEED_API: bool = True
    SEED_ON_STARTUP: bool = False

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8083
    LOG_LEVEL: str = "INFO"

    # Dev-only permissive CORS so a separately-served webui can call this
    # service directly. The Vite/nginx proxy avoids CORS in the normal setup;
    # this is default-on in compose and should be disabled in production.
    ENABLE_DEV_CORS: bool = True

    model_config = SettingsConfigDict(
        env_prefix="AGENTRT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]

# Auth config (AGENTRT_AUTH_ISSUER, _AUDIENCE, _JWKS_URI, _IDENTITY_BASE_URL,
# _INTERNAL_TOKEN, _AUTH_DISABLED, ...).
auth_settings: AuthSettings = load_auth_settings("AGENTRT_")
