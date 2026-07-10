from __future__ import annotations

from typing import Dict

from .base import ProviderAdapter
from .bedrock import BedrockAdapter
from .google_genai import GoogleGenAIAdapter
from .google_vertexai import GoogleVertexAIAdapter
from .openai import OpenAIAdapter

_REGISTRY: Dict[str, ProviderAdapter] = {
    "openai": OpenAIAdapter(),
    "google_genai": GoogleGenAIAdapter(),
    "google_vertexai": GoogleVertexAIAdapter(),
    "bedrock": BedrockAdapter(),
}


def get_provider_adapter(provider: str) -> ProviderAdapter:
    p = (provider or "").strip()
    if not p:
        raise ValueError("ModelProfile.provider must be a non-empty string.")
    if p not in _REGISTRY:
        raise ValueError(f"Unsupported provider '{p}'. Supported: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[p]