from __future__ import annotations

from typing import Any, Dict, Optional

from polyllm.config import ModelProfile
from polyllm.secrets import SecretProvider

from .base import ProviderAdapter


class BedrockAdapter(ProviderAdapter):
    def create_chat_model(
        self,
        profile: ModelProfile,
        *,
        api_key: Optional[str],
        credentials: Dict[str, str],
        secrets: SecretProvider,
    ) -> Any:
        try:
            from langchain_aws import ChatBedrock
        except Exception as e:
            raise RuntimeError(
                "Missing dependency for Bedrock. Install with: pip install polyllm[langchain]"
            ) from e

        kwargs: Dict[str, Any] = {"model_id": profile.model}

        if profile.aws_region:
            kwargs["region_name"] = profile.aws_region

        if profile.timeout_seconds is not None:
            try:
                from botocore.config import Config as BotocoreConfig
            except ImportError as exc:
                raise RuntimeError(
                    "botocore is required to set timeout_seconds for Bedrock. "
                    "It is bundled with boto3/langchain-aws."
                ) from exc
            t = int(profile.timeout_seconds)
            kwargs["config"] = BotocoreConfig(read_timeout=t, connect_timeout=t)

        # Explicit credentials via secret_refs (access_key + secret_key required; session_token optional)
        if credentials:
            if "access_key" not in credentials or "secret_key" not in credentials:
                raise ValueError(
                    "Bedrock explicit credentials require both 'access_key' and 'secret_key' in secret_refs."
                )
            kwargs["aws_access_key_id"] = credentials["access_key"]
            kwargs["aws_secret_access_key"] = credentials["secret_key"]
            if "session_token" in credentials:
                kwargs["aws_session_token"] = credentials["session_token"]
        elif profile.aws_profile:
            # Named AWS profile from ~/.aws/credentials
            kwargs["credentials_profile_name"] = profile.aws_profile
        # else: ambient credentials (IAM role / env vars AWS_* / default profile)

        model_kwargs: Dict[str, Any] = {"temperature": profile.temperature}
        if profile.max_tokens is not None:
            model_kwargs["max_tokens"] = profile.max_tokens
        kwargs["model_kwargs"] = model_kwargs

        if profile.max_retries is not None:
            kwargs["max_retries"] = profile.max_retries

        # Non-secret passthrough
        kwargs.update(profile.provider_options or {})

        return ChatBedrock(**kwargs)