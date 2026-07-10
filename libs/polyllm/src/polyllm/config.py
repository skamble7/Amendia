from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

Transport = Literal["direct", "vertex", "bedrock", "gateway"]


class ModelProfile(BaseModel):
    """
    Non-secret configuration for a model/profile.

    Secrets are never embedded here. Instead reference secrets via:
      - api_key_ref (single-key providers)
      - secret_refs (multi-credential providers; Option A)
      - api_key_env (deprecated / backward compatible)
    """

    provider: str
    model: str
    transport: Transport = "direct"

    # Common generation params
    temperature: float = 0.1
    max_tokens: Optional[int] = None

    # Optional endpoint override (OpenAI-compatible gateways etc.)
    base_url: Optional[str] = None

    # Optional request tuning (non-secret)
    timeout_seconds: Optional[float] = None
    max_retries: Optional[int] = None

    # Useful for gateways / custom routing (non-secret)
    headers: Dict[str, str] = Field(default_factory=dict)
    query_params: Dict[str, str] = Field(default_factory=dict)

    # Non-secret provider-specific kwargs passthrough.
    # Example: {"top_p": 0.95, "safety_settings": [...], "convert_system_message_to_human": True}
    provider_options: Dict[str, Any] = Field(default_factory=dict)

    # When True, polyllm requests structured JSON output from the provider:
    #   - openai: response_format={"type": "json_object"} (guarantees raw JSON)
    #   - google_genai: response_mime_type="application/json" (guarantees raw JSON)
    #   - bedrock: code fences stripped from response text post-call (no API-level JSON mode)
    json_mode: bool = False

    # ─────────────────────────────────────────────────────────────
    # Secrets (references only; never store secret values here)
    # ─────────────────────────────────────────────────────────────

    api_key_ref: Optional[str] = None
    secret_refs: Dict[str, str] = Field(default_factory=dict)
    api_key_env: Optional[str] = None  # deprecated

    # ─────────────────────────────────────────────────────────────
    # Provider-specific non-secret fields
    # ─────────────────────────────────────────────────────────────

    # Google Vertex AI (non-secret)
    gcp_project: Optional[str] = None
    gcp_location: Optional[str] = None

    # AWS Bedrock (non-secret)
    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None


class PolyllmConfig(BaseModel):
    default_profile: str = "default"
    profiles: Dict[str, ModelProfile]
    metadata: Dict[str, Any] = Field(default_factory=dict)