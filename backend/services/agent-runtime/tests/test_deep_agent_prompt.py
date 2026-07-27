# tests/test_deep_agent_prompt.py
"""ADR-047 — a deep_agent's system prompt must be descriptor-framed (title + description), mirroring the llm
path (`run_real_llm`). The capability's registered `description` is the ONLY channel that carries its behavioural
rules to the live model — there is no prompt-registry resolution for `prompt_key` today — so a rule authored in
the description (e.g. `wire-repair-agentic`'s resolution→verdict mapping) must appear verbatim in the outgoing
system prompt. These are pure prompt-construction assertions — no live LLM, no deepagents SDK.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.engine.executor.deep_agent import build_system_prompt


def test_system_prompt_includes_title_and_description():
    prompt = build_system_prompt(
        capability_id="cap.payment.assess_beneficiary_agentic",
        title="Assess beneficiary repairability",
        description="RULE: if info_resolution is present its outcome is authoritative.",
        prompt_key="prompt.payment.assess_beneficiary_agentic",
        schema_hint="",
    )
    assert "cap.payment.assess_beneficiary_agentic" in prompt
    assert "Assess beneficiary repairability" in prompt          # title framed in
    assert "info_resolution is present its outcome is authoritative" in prompt  # description delivered verbatim
    assert "prompt.payment.assess_beneficiary_agentic" in prompt  # prompt_key stays as the task label


def test_system_prompt_degrades_without_descriptor():
    # title/description are optional — an undescribed capability still yields a valid, framing-free prompt.
    prompt = build_system_prompt("cap.x", None, None, "task.x")
    assert "cap.x" in prompt and "task.x" in prompt
    assert "Use ONLY the provided tools" in prompt


def test_agentic_assess_mapping_reaches_the_prompt_from_the_seed():
    # End-to-end at the seed level: the mapping authored in the real capability's description is present in the
    # prompt the model would receive. This is the assertion that would have caught the "reaches the model through
    # zero channels" gap.
    root = Path(__file__).resolve().parents[1] / "seed" / "wire-repair-agentic" / "capabilities"
    desc = json.loads((root / "cap.payment.assess_beneficiary_agentic.json").read_text())
    prompt = build_system_prompt(desc["capability_id"], desc.get("title"), desc.get("description"),
                                 desc["runtime"]["prompt_key"])
    assert "'resolved'" in prompt and "repairable" in prompt
    assert "'cannot_obtain'" in prompt and "unrepairable" in prompt
    assert "AUTHORITATIVE" in prompt
