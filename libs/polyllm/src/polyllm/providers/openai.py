from __future__ import annotations

from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider

from .base import ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        if not api_key:
            raise ValueError(
                "OpenAI requires an API key. Provide api_key_ref (preferred) or api_key_env (deprecated)."
            )

        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:
            raise RuntimeError(
                "Missing dependency for OpenAI. Install with: pip install polyllm[langchain]"
            ) from e

        kwargs: Dict[str, Any] = {
            "model": profile.model,
            "temperature": profile.temperature,
            "api_key": api_key,
        }

        if profile.base_url:
            kwargs["base_url"] = profile.base_url
        if profile.max_tokens is not None:
            kwargs["max_tokens"] = profile.max_tokens
        if profile.timeout_seconds is not None:
            kwargs["timeout"] = profile.timeout_seconds
        if profile.max_retries is not None:
            kwargs["max_retries"] = profile.max_retries

        if profile.json_mode:
            model_kw = kwargs.get("model_kwargs") or {}
            model_kw.setdefault("response_format", {"type": "json_object"})
            kwargs["model_kwargs"] = model_kw

        # Non-secret passthrough (be careful what you allow here in enterprise policy)
        kwargs.update(profile.provider_options or {})

        return ChatOpenAI(**kwargs)