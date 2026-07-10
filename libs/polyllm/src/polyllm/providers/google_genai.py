from __future__ import annotations

from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider

from .base import ProviderAdapter


class GoogleGenAIAdapter(ProviderAdapter):
    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        if not api_key:
            raise ValueError("google_genai requires an API key. Provide api_key_ref.")

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except Exception as e:
            raise RuntimeError(
                "Missing dependency for Google GenAI. Install with: pip install polyllm[langchain]"
            ) from e

        kwargs: Dict[str, Any] = {
            "model": profile.model,
            "temperature": profile.temperature,
            "google_api_key": api_key,
        }

        # Gemini nuance: max_output_tokens (not max_tokens)
        if profile.max_tokens is not None:
            kwargs["max_output_tokens"] = profile.max_tokens

        # Some versions accept timeout / retries; keep guarded and allow override via provider_options.
        if profile.timeout_seconds is not None:
            kwargs.setdefault("timeout", profile.timeout_seconds)
        if profile.max_retries is not None:
            kwargs.setdefault("max_retries", profile.max_retries)

        if profile.json_mode:
            kwargs.setdefault("response_mime_type", "application/json")

        kwargs.update(profile.provider_options or {})

        return ChatGoogleGenerativeAI(**kwargs)