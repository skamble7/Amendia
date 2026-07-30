# app/services/copilot/llm.py
"""The copilot's single semantic LLM call — reuses the shared polyllm + ConfigForge stack (ADR-016/017/018),
exactly like agent-runtime's llm/deep_agent capabilities. No bespoke provider client.

Design mirrors agent-runtime's ``dispatch._llm_client`` seam:
  * ``_llm_client(ref)`` — a module-level cache keyed by ConfigForge ref; resolves a ``ModelProfile`` by ref via
    polyllm's ``RemoteConfigLoader`` (secrets stay references, resolved through polyllm's SecretProvider chain —
    never a raw key here). This is the ONE function tests monkeypatch to inject a fake client (no network, no
    ConfigForge, no live model).
  * ``generate_proposal(...)`` — builds the message list, ``await client.chat(...)``, robust-parses the JSON
    (relying on the profile's ``json_mode`` + fence-stripping, plus a provider-agnostic ``_parse_json`` net),
    validates into ``CopilotProposal``, and re-prompts ONCE on a parse/validation miss.

The process-registry routers are async, so we ``await`` the client directly (no sync bridge needed).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.config import settings
from app.services.copilot.proposal import CopilotProposal

logger = logging.getLogger(__name__)

# Per-ref client cache (mirrors agent-runtime's ``dispatch._LLM_CLIENTS``). Tests replace ``_llm_client``.
_LLM_CLIENTS: Dict[str, Any] = {}


class CopilotLLMError(Exception):
    """The semantic call could not produce a valid proposal (disabled, unreachable, or unparseable)."""


def _run_blocking(coro: Any) -> Any:
    """Run an async coroutine to completion from any context (copied from agent-runtime's executor bridge). A
    running loop is present here (async router), so isolate the resolve on a worker thread."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _llm_client(ref: str) -> Any:
    """Resolve (and cache, keyed on the RESOLVED ref) the polyllm ``LLMClient`` for a ConfigForge ref — the
    provider/model/base_url/params all come from the ConfigForge ModelProfile (nothing hardcoded), and provider
    secrets stay references resolved through polyllm's SecretProvider chain (ADR-016 trap 1). Sync + lazy-imports
    polyllm so the module loads without it and so tests can monkeypatch THIS function (``lambda ref: fake``) to
    bypass ConfigForge and the network. An unknown ref or an unreachable ConfigForge raises a clean
    ``CopilotLLMError`` naming the ref — never a crash, and NEVER a silent fall-back to some default model."""
    client = _LLM_CLIENTS.get(ref)
    if client is None:
        try:
            from polyllm import RemoteConfigLoader  # lazy — only the real path needs polyllm[remote]

            loader = RemoteConfigLoader(base_url=settings.CONFIG_FORGE_URL)
            client = _run_blocking(loader.load(ref))
        except CopilotLLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - unknown ref / ConfigForge down / bad profile → explicit, no fallback
            raise CopilotLLMError(
                f"could not resolve model config ref '{ref}' from ConfigForge at "
                f"{settings.CONFIG_FORGE_URL}: {type(exc).__name__}: {exc}"
            ) from exc
        _LLM_CLIENTS[ref] = client
    return client


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Robust JSON extraction (mirrors agent-runtime's ``dispatch._parse_json``): strip code fences, then
    ``json.loads``; on failure fall back to the substring between the first ``{`` and the last ``}``."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        # drop a leading ```lang fence and a trailing ```
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        s = s.split("\n", 1)[1] if s[:4].lower() in ("json", "json") and "\n" in s else s
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    lo, hi = s.find("{"), s.rfind("}")
    if lo >= 0 and hi > lo:
        try:
            obj = json.loads(s[lo:hi + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


async def _call_structured(*, ref: str, messages: List[Dict[str, str]], model_cls: Any) -> Tuple[Any, str]:
    """Make the semantic call and return a ``model_cls`` instance + the ref actually used. Same ConfigForge/
    fake seam, robust JSON parse, and single re-prompt (feeding the exact miss back) for every structured call —
    the copilot's generation (2a) and conversational refine (2b) both go through here."""
    if settings.COPILOT_LLM_DISABLED:
        raise CopilotLLMError(
            "copilot LLM is disabled (REGISTRY_COPILOT_LLM_DISABLED) — inject a proposal/fake client to generate"
        )
    client = _llm_client(ref)
    convo = list(messages)
    err = "no response"
    for attempt in (1, 2):
        result = await client.chat(convo)
        text = getattr(result, "text", "") or ""
        data = _parse_json(text)
        if data is not None:
            try:
                return model_cls.model_validate(data), ref
            except ValidationError as exc:
                err = f"the JSON did not match {model_cls.__name__}: {exc.errors()[:3]}"
        else:
            err = "the response was not valid JSON"
        logger.warning("copilot LLM (%s) attempt %d/2 failed: %s", model_cls.__name__, attempt, err)
        if attempt == 1:
            convo = convo + [
                {"role": "assistant", "content": text[:4000]},
                {"role": "user", "content": f"That response was rejected: {err}. "
                                             f"Return ONLY the corrected JSON object — no prose, no code fences."},
            ]
    raise CopilotLLMError(f"the copilot LLM did not return a valid {model_cls.__name__} after 2 attempts: {err}")


async def generate_proposal(*, ref: str, messages: List[Dict[str, str]]) -> Tuple[CopilotProposal, str]:
    """2a: the semantic call that returns a validated CopilotProposal."""
    return await _call_structured(ref=ref, messages=messages, model_cls=CopilotProposal)


async def interpret_edit(*, ref: str, messages: List[Dict[str, str]]) -> Tuple[Any, str]:
    """2b: interpret a natural-language refine message into a validated CopilotEdit (typed mutations or a
    clarifying question). Imported lazily to avoid a module import cycle (mutations → proposal, not llm)."""
    from app.services.copilot.mutations import CopilotEdit
    return await _call_structured(ref=ref, messages=messages, model_cls=CopilotEdit)
