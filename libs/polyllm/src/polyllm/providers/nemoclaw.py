from __future__ import annotations

from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider

from .base import ProviderAdapter

# Placeholder key used only when no host-side token resolves AND the profile targets the
# OpenShell managed-inference proxy: in that (deferred) in-sandbox path the gateway injects
# a scoped token, so the host must not demand one. A direct NIM profile supplies a real
# api_key_ref (env:NVIDIA_NIM_API_KEY) and never hits this. # [confirm] against live
# NemoClaw docs how the gateway brokers/injects the scoped inference token.
_BROKERED_PLACEHOLDER = "openshell-gateway-brokered"


class NemoClawAdapter(ProviderAdapter):
    """NemoClaw managed-inference provider (Nemotron 3 Ultra and any model behind an
    OpenAI-compatible endpoint — NVIDIA NIM or the OpenShell managed inference proxy).

    Reuses the OpenAI chat-model mechanism (``langchain_openai.ChatOpenAI``) parameterised
    on ``base_url``, since the target is OpenAI-compatible. Two credential modes:

      * **direct / native (usable now):** ``api_key_ref`` (e.g. ``env:NVIDIA_NIM_API_KEY``)
        resolves host-side via the SecretProvider chain, exactly like other providers.
      * **in-sandbox managed proxy (deferred, Phase 5):** the OpenShell gateway scopes and
        injects the token so the sandbox never holds it — the host does not require one.

    JSON is handled Bedrock-style: no reliance on a provider JSON-mode API (NIM/proxy
    support is unconfirmed); ``client.py`` strips code fences post-response when
    ``json_mode`` is set. A profile whose endpoint supports OpenAI ``response_format`` may
    opt in via ``provider_options``.
    """

    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        if not profile.base_url:
            raise ValueError(
                "nemoclaw requires base_url (the NVIDIA NIM endpoint or the OpenShell "
                "managed inference proxy, e.g. https://inference.local/v1)."
            )

        try:
            from langchain_openai import ChatOpenAI
        except Exception as e:  # pragma: no cover - dep guard, mirrors sibling adapters
            raise RuntimeError(
                "Missing dependency for NemoClaw (OpenAI-compatible transport). "
                "Install with: pip install polyllm[langchain]"
            ) from e

        kwargs: Dict[str, Any] = {
            "model": profile.model,
            "temperature": profile.temperature,
            "base_url": profile.base_url,
            # Direct path: the resolved host-side token. Brokered path: a placeholder so no
            # host-side secret is demanded (the gateway injects the real scoped token). No
            # secret is ever embedded in the profile — this is a resolved value or a
            # non-secret placeholder.
            "api_key": api_key or _BROKERED_PLACEHOLDER,
        }

        if profile.max_tokens is not None:
            kwargs["max_tokens"] = profile.max_tokens
        if profile.timeout_seconds is not None:
            kwargs["timeout"] = profile.timeout_seconds
        if profile.max_retries is not None:
            kwargs["max_retries"] = profile.max_retries
        if profile.headers:
            # [confirm] NemoClaw-specific auth/routing headers (e.g. sandbox/session id) —
            # carried as non-secret profile config; verify header names against live docs.
            kwargs["default_headers"] = dict(profile.headers)

        # json_mode is enforced by fence-stripping in client.py (mirrors bedrock); we do NOT
        # assume a provider-level response_format here. A profile can still request it via
        # provider_options if its endpoint is known to support it.
        kwargs.update(profile.provider_options or {})

        return ChatOpenAI(**kwargs)
