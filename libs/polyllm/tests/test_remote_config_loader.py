# libs/polyllm/tests/test_remote_config_loader.py
"""
Unit tests for RemoteConfigLoader.

All HTTP calls are mocked — no network access required.
Tests cover:
  - Constructor: explicit base_url, env-var fallback, missing URL error, trailing slash
  - load(): happy path, URL construction, profile mapping, HTTP errors, timeout forwarding
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polyllm import RemoteConfigLoader
from polyllm.client import LLMClient

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_URL = "http://localhost:8040"

# Minimal valid ConfigForge response payload for an OpenAI LLM config
_OPENAI_PAYLOAD = {
    "ref": "prod.llm.openai.astra.primary",
    "env": "prod",
    "kind": "llm",
    "provider": "openai",
    "platform": "astra",
    "name": "primary",
    "data": {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.1,
        "api_key_ref": "env:OPENAI_API_KEY",
    },
}

_BEDROCK_PAYLOAD = {
    "ref": "prod.llm.bedrock.zeta.modernization",
    "data": {
        "provider": "bedrock",
        "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "aws_region": "us-east-1",
        "secret_refs": {
            "access_key": "env:AWS_ACCESS_KEY_ID",
            "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        },
    },
}


def _mock_http(json_payload: dict | None = None, raise_for_status_exc: Exception | None = None):
    """
    Build a mock httpx.AsyncClient async context manager.

    Returns a mock that behaves like:
        async with httpx.AsyncClient(timeout=...) as http:
            response = await http.get(url)
            response.raise_for_status()
            payload = response.json()
    """
    mock_response = MagicMock()
    if raise_for_status_exc:
        mock_response.raise_for_status.side_effect = raise_for_status_exc
    else:
        mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = json_payload or {}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------

def test_init_raises_if_neither_base_url_nor_env_var_set(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    with pytest.raises(ValueError, match="CONFIG_FORGE_URL"):
        RemoteConfigLoader()


def test_init_explicit_base_url_stored(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    assert loader.base_url == _BASE_URL


def test_init_trailing_slash_stripped(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url="http://localhost:8040/")
    assert loader.base_url == "http://localhost:8040"


def test_init_reads_config_forge_url_from_env(monkeypatch):
    monkeypatch.setenv("CONFIG_FORGE_URL", "http://config-forge-service:8040")
    loader = RemoteConfigLoader()
    assert loader.base_url == "http://config-forge-service:8040"


def test_init_env_var_trailing_slash_stripped(monkeypatch):
    monkeypatch.setenv("CONFIG_FORGE_URL", "http://config-forge-service:8040/")
    loader = RemoteConfigLoader()
    assert loader.base_url == "http://config-forge-service:8040"


def test_init_explicit_base_url_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("CONFIG_FORGE_URL", "http://env-url:8040")
    loader = RemoteConfigLoader(base_url="http://explicit:9999")
    assert loader.base_url == "http://explicit:9999"


def test_init_default_timeout_is_five(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    assert loader.timeout == 5.0


def test_init_custom_timeout_stored(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL, timeout=30.0)
    assert loader.timeout == 30.0


# ---------------------------------------------------------------------------
# load() — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_returns_llm_client(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    assert isinstance(client, LLMClient)


@pytest.mark.asyncio
async def test_load_constructs_correct_url(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    mock_client = _mock_http(_OPENAI_PAYLOAD)
    with patch("httpx.AsyncClient", return_value=mock_client):
        await loader.load("prod.llm.openai.astra.primary")
    mock_client.get.assert_called_once_with(
        "http://localhost:8040/config/resolve/prod.llm.openai.astra.primary"
    )


@pytest.mark.asyncio
async def test_load_url_uses_env_var_base_url(monkeypatch):
    monkeypatch.setenv("CONFIG_FORGE_URL", "http://config-forge-service:8040")
    loader = RemoteConfigLoader()
    mock_client = _mock_http(_OPENAI_PAYLOAD)
    with patch("httpx.AsyncClient", return_value=mock_client):
        await loader.load("prod.llm.openai.astra.primary")
    mock_client.get.assert_called_once_with(
        "http://config-forge-service:8040/config/resolve/prod.llm.openai.astra.primary"
    )


@pytest.mark.asyncio
async def test_load_maps_provider_from_payload(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    profile = client.cfg.profiles["default"]
    assert profile.provider == "openai"


@pytest.mark.asyncio
async def test_load_maps_model_from_payload(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    profile = client.cfg.profiles["default"]
    assert profile.model == "gpt-4o"


@pytest.mark.asyncio
async def test_load_maps_temperature_from_payload(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    profile = client.cfg.profiles["default"]
    assert profile.temperature == 0.1


@pytest.mark.asyncio
async def test_load_maps_api_key_ref_from_payload(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    profile = client.cfg.profiles["default"]
    assert profile.api_key_ref == "env:OPENAI_API_KEY"


@pytest.mark.asyncio
async def test_load_maps_bedrock_secret_refs(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_BEDROCK_PAYLOAD)):
        client = await loader.load("prod.llm.bedrock.zeta.modernization")
    profile = client.cfg.profiles["default"]
    assert profile.provider == "bedrock"
    assert profile.secret_refs == {
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
    }


@pytest.mark.asyncio
async def test_load_profile_is_stored_under_default_key(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)):
        client = await loader.load("prod.llm.openai.astra.primary")
    assert "default" in client.cfg.profiles
    assert client.cfg.default_profile == "default"


# ---------------------------------------------------------------------------
# load() — timeout forwarding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_forwards_timeout_to_http_client(monkeypatch):
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL, timeout=15.0)
    with patch("httpx.AsyncClient", return_value=_mock_http(_OPENAI_PAYLOAD)) as mock_cls:
        await loader.load("prod.llm.openai.astra.primary")
    mock_cls.assert_called_once_with(timeout=15.0)


# ---------------------------------------------------------------------------
# load() — HTTP error propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_propagates_http_404(monkeypatch):
    import httpx as _httpx
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    exc = _httpx.HTTPStatusError(
        "404 Not Found",
        request=MagicMock(),
        response=MagicMock(status_code=404),
    )
    with patch("httpx.AsyncClient", return_value=_mock_http(raise_for_status_exc=exc)):
        with pytest.raises(_httpx.HTTPStatusError):
            await loader.load("dev.llm.openai.does-not-exist")


@pytest.mark.asyncio
async def test_load_propagates_http_500(monkeypatch):
    import httpx as _httpx
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    exc = _httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=MagicMock(status_code=500),
    )
    with patch("httpx.AsyncClient", return_value=_mock_http(raise_for_status_exc=exc)):
        with pytest.raises(_httpx.HTTPStatusError):
            await loader.load("prod.llm.openai.astra.primary")


@pytest.mark.asyncio
async def test_load_propagates_connection_error(monkeypatch):
    import httpx as _httpx
    monkeypatch.delenv("CONFIG_FORGE_URL", raising=False)
    loader = RemoteConfigLoader(base_url=_BASE_URL)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(_httpx.ConnectError):
            await loader.load("prod.llm.openai.astra.primary")
