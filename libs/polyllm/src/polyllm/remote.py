from __future__ import annotations

import os
from typing import Optional

from .client import LLMClient
from .config import ModelProfile, PolyllmConfig
from .secrets import SecretProvider, default_secret_provider

_ENV_VAR = "CONFIG_FORGE_URL"


class RemoteConfigLoader:
    """
    Fetches a ModelProfile from ConfigForge by canonical ref and returns a ready LLMClient.

    The canonical ref format is: {env}.{kind}[.{provider}][.{platform}].{name}
    Examples:
        prod.llm.openai.default
        prod.llm.openai.astra.primary
        dev.llm.bedrock.zeta.modernization

    Usage (base_url read from CONFIG_FORGE_URL env var):
        loader = RemoteConfigLoader()
        client = await loader.load("prod.llm.openai.astra.primary")
        result = await client.chat([{"role": "user", "content": "Hello"}])

    Usage (explicit base_url):
        loader = RemoteConfigLoader(base_url="http://config-forge-service:8040")
        client = await loader.load("prod.llm.openai.astra.primary")

    Requires: pip install polyllm[remote]
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        secrets: Optional[SecretProvider] = None,
        timeout: float = 5.0,
    ) -> None:
        resolved = base_url or os.environ.get(_ENV_VAR)
        if not resolved:
            raise ValueError(
                f"ConfigForge URL not provided. Either pass base_url= or set the "
                f"{_ENV_VAR} environment variable."
            )
        self.base_url = resolved.rstrip("/")
        self.secrets = secrets or default_secret_provider()
        self.timeout = timeout

    async def load(self, ref: str) -> LLMClient:
        """Fetch config by canonical ref from ConfigForge and return an initialized LLMClient."""
        try:
            import httpx
        except ImportError as e:
            raise ImportError(
                "Missing dependency for RemoteConfigLoader. Install with: pip install polyllm[remote]"
            ) from e

        url = f"{self.base_url}/config/resolve/{ref}"
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            response = await http.get(url)
            response.raise_for_status()

        payload = response.json()
        profile = ModelProfile(**payload["data"])
        cfg = PolyllmConfig(profiles={"default": profile})
        return LLMClient(cfg, secrets=self.secrets)
