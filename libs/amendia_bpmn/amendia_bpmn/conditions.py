# amendia_bpmn/conditions.py
"""The ONE canonical gateway-condition grammar — the single source of truth both agent-runtime (runtime
evaluation) and process-registry (design-time validation) import, so the two can never drift again.

Supported runtime subset (whitespace-tolerant; both ``=`` and ``==`` accepted):

    <dotpath> = "literal"
    <dotpath> != "literal"

``<dotpath>``'s first segment is the produced output artifact name; the rest is a field path into it. Anything
else is outside the subset (``ConditionSyntaxError`` at runtime; a guided, blocking finding at design time).

This module is PURE (no I/O). It provides:
  * ``CONDITION_RE`` / ``parse_condition`` — the runtime arbiter (agent-runtime delegates here byte-for-byte);
  * ``normalize_condition`` — the Tier-1 *lossless* transforms applied at BPMN extraction (unwrap ``${…}``,
    single→double quotes) — never anything that could change which branch fires;
  * ``classify_condition_error`` — a machine reason for a non-canonical residue, to build guided messages.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# The arbiter. MUST stay byte-identical to agent-runtime's historical ``expr._COND``.
CONDITION_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*(==|=|!=)\s*"([^"]*)"\s*$')

# A loose LHS grabber (first identifier dotpath) — used for guided messages + the field-less check even when
# the whole condition does not parse. Mirrors registry ``inference._CONDITION_LHS`` / ``pack_validator._COND_LHS``.
_LHS_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.]*)')

# Operators/keywords the subset does NOT support (a guided "compute upstream, branch on a string" message).
_UNSUPPORTED_OP_RE = re.compile(r'(>=|<=|<>|>|<|&&|\|\||\band\b|\bor\b|\bnot\b|\bin\b|\bcontains\b|\bmatches\b)', re.I)


class ConditionSyntaxError(ValueError):
    """The gateway flow condition is outside the supported subset."""


def parse_condition(expr: str) -> Tuple[List[str], str, str]:
    """Return ``(segments, op, literal)`` where op is ``"=="`` or ``"!="``. Raises ``ConditionSyntaxError``
    outside the subset. Byte-identical to agent-runtime's historical parser (which now delegates here)."""
    m = CONDITION_RE.match(expr or "")
    if not m:
        raise ConditionSyntaxError(f"unsupported gateway condition expression: {expr!r}")
    path, op, literal = m.group(1), m.group(2), m.group(3)
    return path.split("."), ("!=" if op == "!=" else "=="), literal


def condition_lhs(expr: Optional[str]) -> Optional[str]:
    """The condition's LHS dotpath (best-effort, even when the whole expression doesn't parse), or None."""
    if not expr:
        return None
    m = _LHS_RE.match(expr)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Tier-1 — lossless normalization (applied at the BPMN extraction seam)
# --------------------------------------------------------------------------- #
def normalize_condition(raw: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Return ``(canonical, changes)`` applying ONLY provably truth-preserving transforms:

      * strip a **balanced outer** ``${ … }`` / ``#{ … }`` wrapper (Camunda/generic modelers) — only when the
        whole trimmed body is a single wrapper;
      * convert an **outermost** single-quoted string literal to double-quoted (``'approve'`` → ``"approve"``) —
        only when unambiguous (exactly two single quotes, no double quotes present).

    Idempotent; a no-op returns ``(raw, [])``. Anything ambiguous or not-clearly-lossless (a literal containing
    a ``"``, nested/unbalanced braces, multiple quoted parts) is **left untouched** for validation to flag —
    better to flag than to mis-rewrite and silently change which branch fires."""
    if raw is None:
        return None, []
    changes: List[str] = []
    s = raw.strip()

    inner = _strip_balanced_wrapper(s)
    if inner is not None and inner != s:
        wrapper = s[0]  # '$' or '#'
        changes.append(f"unwrapped {wrapper}{{…}} expression")
        s = inner.strip()

    dq = _single_to_double_quotes(s)
    if dq is not None and dq != s:
        changes.append("converted single-quoted literal to double-quoted")
        s = dq

    return s, changes


def _strip_balanced_wrapper(s: str) -> Optional[str]:
    """If ``s`` is exactly one ``${ … }`` / ``#{ … }`` wrapper (the closing brace matches the opener AND is the
    last char), return the inner body; else None (unbalanced / not-whole-body-wrapped → leave it alone)."""
    if len(s) < 3 or s[0] not in "$#" or s[1] != "{" or s[-1] != "}":
        return None
    depth = 1
    for i in range(2, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[2:i] if i == len(s) - 1 else None  # only when it wraps the WHOLE body
    return None  # never closed (unbalanced)


def _single_to_double_quotes(s: str) -> Optional[str]:
    """Convert an outermost single-quoted literal to double-quoted — only when unambiguous: exactly two single
    quotes and no double quote anywhere (a ``"`` inside would make the rewrite lossy/ambiguous → leave it)."""
    if "'" not in s or '"' in s:
        return None
    if s.count("'") != 2:  # nested/multiple → ambiguous, leave for validation
        return None
    i, j = s.index("'"), s.rindex("'")
    return s[:i] + '"' + s[i + 1:j] + '"' + s[j + 1:]


# --------------------------------------------------------------------------- #
# Tier-2 — classify a non-canonical residue (for guided, blocking messages)
# --------------------------------------------------------------------------- #
def classify_condition_error(canonical: str) -> str:
    """A machine reason for why ``canonical`` is not a valid runtime condition:
    ``wrapper_unresolved`` | ``unsupported_operator`` | ``unquoted_rhs`` | ``not_parseable``. (``missing_field``
    — a field-less LHS that parses but can never branch — is detected separately by the validator.)"""
    s = (canonical or "").strip()
    if "${" in s or "#{" in s or "{" in s or "}" in s:
        return "wrapper_unresolved"
    if _UNSUPPORTED_OP_RE.search(s):
        return "unsupported_operator"
    m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(==|=|!=)\s*(.+?)\s*$', s)
    if m:
        rhs = m.group(3).strip()
        if not (len(rhs) >= 2 and rhs.startswith('"') and rhs.endswith('"')):
            return "unquoted_rhs"
    return "not_parseable"
