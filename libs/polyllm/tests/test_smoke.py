# libs/polyllm/tests/test_smoke.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pytest

from polyllm import LLMClient, PolyllmConfig


SECRETS_FILE = "./secrets.local.json"

EXPECTED_SENTENCE = (
    "polyllm is a config-driven, provider-agnostic LLM client library that lets apps "
    "switch providers/models without code changes."
)


def _load_local_secrets(file_path: str) -> dict:
    p = Path(file_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_real_local_key(file_path: str, key_name: str) -> bool:
    data = _load_local_secrets(file_path)
    v = data.get(key_name)
    if not isinstance(v, str) or not v.strip():
        return False
    if v.strip() in {"sk-...", "AIza..."}:
        return False
    if key_name == "OPENAI_API_KEY":
        return v.strip().startswith("sk-")
    if key_name == "GEMINI_API_KEY":
        return v.strip().startswith("AIza")
    return True


def _has_aws_keys(file_path: str) -> bool:
    return _has_real_local_key(file_path, "AWS_ACCESS_KEY_ID") and _has_real_local_key(
        file_path, "AWS_SECRET_ACCESS_KEY"
    )


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _one_sentenceish(text: str) -> bool:
    """
    Heuristic: treat as 1 sentence if it doesn't contain multiple sentence-ending punctuations.
    (Keeps us from failing on tiny variations.)
    """
    t = (text or "").strip()
    if not t:
        return False
    # Count sentence terminators. Allow one.
    terminators = re.findall(r"[.!?]+", t)
    return len(terminators) <= 1


def _assert_contains_all(text: str, required: Iterable[str]) -> None:
    t = _norm(text)
    missing = [r for r in required if _norm(r) not in t]
    if missing:
        raise AssertionError(f"Missing required phrases: {missing}\nGot:\n{text}")


def test_config_load_smoke():
    cfg = PolyllmConfig(
        default_profile="default",
        profiles={
            "default": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_ref": f"file:{SECRETS_FILE}#OPENAI_API_KEY",
            }
        },
    )
    client = LLMClient(cfg)
    assert client.cfg.default_profile == "default"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_openai_chat_integration_json_contract():
    if not _has_real_local_key(SECRETS_FILE, "OPENAI_API_KEY"):
        pytest.skip("secrets.local.json missing or OPENAI_API_KEY looks like a placeholder")

    cfg = PolyllmConfig(
        default_profile="openai",
        profiles={
            "openai": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_ref": f"file:{SECRETS_FILE}#OPENAI_API_KEY",
                "temperature": 0.1,
                "max_tokens": 256,
                "timeout_seconds": 60,
                "max_retries": 2,
            }
        },
    )

    client = LLMClient(cfg)

    prompt = (
        "Return ONLY valid JSON. No markdown, no extra text.\n"
        'Schema: { "ok": true, "summary": "<exact sentence>" }\n'
        f'The "summary" MUST be exactly:\n"{EXPECTED_SENTENCE}"\n'
    )

    result = await client.chat(
        [
            {"role": "system", "content": "You are a strict JSON emitter."},
            {"role": "user", "content": prompt},
        ],
        profile="openai",
    )

    print("\n[polyllm integration] provider=openai model=gpt-4o-mini")
    print(result.text)

    obj = json.loads(result.text)
    assert obj["ok"] is True
    assert _norm(obj["summary"]) == _norm(EXPECTED_SENTENCE)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_genai_chat_integration_text_capability_contract():
    """
    Google GenAI (Gemini) is not reliably "verbatim" even at low temperature.
    So this integration test verifies a stable *capability contract*:

    - returns non-empty output
    - output is roughly one sentence
    - output contains required meaning-bearing phrases
    - provider/model in result.raw matches the profile selection
    """
    if not _has_real_local_key(SECRETS_FILE, "GEMINI_API_KEY"):
        pytest.skip("secrets.local.json missing or GEMINI_API_KEY looks like a placeholder")

    cfg = PolyllmConfig(
        default_profile="gemini",
        profiles={
            "gemini": {
                "provider": "google_genai",
                "model": "gemini-flash-latest",
                "api_key_ref": f"file:{SECRETS_FILE}#GEMINI_API_KEY",
                "temperature": 0.1,
                # adapter maps this to max_output_tokens
                "max_tokens": 512,
                "timeout_seconds": 60,
                "max_retries": 2,
                "provider_options": {},
            }
        },
    )

    client = LLMClient(cfg)

    prompt = (
        "Write exactly ONE sentence that communicates this meaning:\n"
        f"- {EXPECTED_SENTENCE}\n"
        "Do not use bullet points. Do not add a second sentence."
    )

    result = await client.chat(
        [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
        profile="gemini",
    )

    print("\n[polyllm integration] provider=google_genai model=gemini-flash-latest")
    print(result.text)

    assert isinstance(result.text, str) and result.text.strip()

    # Basic shape
    assert _one_sentenceish(result.text), f"Expected one sentence-ish output.\nGot:\n{result.text}"

    # Ensure routing metadata is correct (this is important for polyllm)
    assert result.raw.get("provider") == "google_genai"
    assert result.raw.get("model") == "gemini-flash-latest"

    # Meaning-bearing phrases (robust against paraphrase)
    _assert_contains_all(
        result.text,
        required=[
            "config",          # config-driven/configuration
            "provider",        # provider/providers
            "model",           # model/models
            "switch",          # switching
            "code changes",    # without code changes / no code changes
        ],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bedrock_chat_integration_text_capability_contract():
    """
    AWS Bedrock (Claude Haiku via Bedrock) capability contract test.

    Verifies:
    - returns non-empty output
    - output is roughly one sentence
    - output contains required meaning-bearing phrases
    - provider/model in result.raw matches the profile selection
    """
    if not _has_aws_keys(SECRETS_FILE):
        pytest.skip("secrets.local.json missing or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set")

    cfg = PolyllmConfig(
        default_profile="bedrock",
        profiles={
            "bedrock": {
                "provider": "bedrock",
                "model": "anthropic.claude-3-haiku-20240307-v1:0",
                "aws_region": "us-east-1",
                "temperature": 0.1,
                "max_tokens": 512,
                "secret_refs": {
                    "access_key": f"file:{SECRETS_FILE}#AWS_ACCESS_KEY_ID",
                    "secret_key": f"file:{SECRETS_FILE}#AWS_SECRET_ACCESS_KEY",
                },
            }
        },
    )

    client = LLMClient(cfg)

    prompt = (
        "Write exactly ONE sentence that communicates this meaning:\n"
        f"- {EXPECTED_SENTENCE}\n"
        "Do not use bullet points. Do not add a second sentence."
    )

    result = await client.chat(
        [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
        profile="bedrock",
    )

    print("\n[polyllm integration] provider=bedrock model=anthropic.claude-3-haiku-20240307-v1:0")
    print(result.text)

    assert isinstance(result.text, str) and result.text.strip()

    assert _one_sentenceish(result.text), f"Expected one sentence-ish output.\nGot:\n{result.text}"

    assert result.raw.get("provider") == "bedrock"
    assert result.raw.get("model") == "anthropic.claude-3-haiku-20240307-v1:0"

    _assert_contains_all(
        result.text,
        required=[
            "config",       # config-driven/configuration
            "provider",     # provider/providers
            "model",        # model/models
            "switch",       # switching
            "code changes", # without code changes / no code changes
        ],
    )