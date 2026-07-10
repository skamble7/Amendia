from __future__ import annotations

from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider

from .base import ProviderAdapter


class GoogleVertexAIAdapter(ProviderAdapter):
    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        raise RuntimeError(
            "google_vertexai adapter not enabled yet. "
            "When ready, add langchain-google-vertexai and implement ADC/service-account handling."
        )