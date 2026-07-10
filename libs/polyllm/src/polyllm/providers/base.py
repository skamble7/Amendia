from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider


class ProviderAdapter(ABC):
    """
    Creates a LangChain chat model (or any backend) for a given profile.
    """

    @abstractmethod
    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        raise NotImplementedError