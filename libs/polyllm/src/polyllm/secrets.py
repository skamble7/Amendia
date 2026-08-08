from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Optional, Protocol, Tuple


class SecretProvider(Protocol):
    def get(self, ref: str) -> Optional[str]:
        raise NotImplementedError


def _split_ref(ref: str) -> Tuple[str, str]:
    ref = (ref or "").strip()
    if ":" not in ref:
        raise ValueError(f"Invalid secret ref '{ref}'. Expected '<scheme>:<value>'.")
    scheme, rest = ref.split(":", 1)
    scheme = scheme.strip().lower()
    rest = rest.strip()
    if not scheme or not rest:
        raise ValueError(f"Invalid secret ref '{ref}'. Expected '<scheme>:<value>'.")
    return scheme, rest


def _split_path_and_key(rest: str) -> Tuple[str, Optional[str]]:
    if "#" in rest:
        path_str, key = rest.split("#", 1)
        key = key.strip() or None
        return path_str.strip(), key
    return rest.strip(), None


class LiteralSecretProvider:
    """Resolves literal:<value> refs — the secret value is embedded directly in the ref.
    Intended for development / config-service stored secrets before Vault migration."""

    scheme: ClassVar[str] = "literal"          # the ref scheme this provider handles (for Composite routing)

    def get(self, ref: str) -> Optional[str]:
        scheme, rest = _split_ref(ref)
        if scheme != "literal":
            raise ValueError(f"LiteralSecretProvider only supports literal:* refs. Got: {ref}")
        return rest  # the value itself IS the secret


class EnvSecretProvider:
    scheme: ClassVar[str] = "env"

    def get(self, ref: str) -> Optional[str]:
        scheme, rest = _split_ref(ref)
        if scheme != "env":
            raise ValueError(f"EnvSecretProvider only supports env:* refs. Got: {ref}")
        env_name = rest.strip()
        return os.getenv(env_name) if env_name else None


@dataclass
class FileSecretProvider:
    scheme: ClassVar[str] = "file"
    default_path: Optional[str] = None
    _cache_path: Optional[str] = None
    _cache_data: Optional[dict] = None

    def _load_json(self, path_str: str) -> dict:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()

        if self._cache_path == str(p) and self._cache_data is not None:
            return self._cache_data

        if not p.exists():
            raise FileNotFoundError(f"Secret file not found: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Secret file must contain a JSON object at top-level: {p}")

        self._cache_path = str(p)
        self._cache_data = data
        return data

    def get(self, ref: str) -> Optional[str]:
        scheme, rest = _split_ref(ref)
        if scheme != "file":
            raise ValueError(f"FileSecretProvider only supports file:* refs. Got: {ref}")

        path_str, key = _split_path_and_key(rest)

        if (not path_str or path_str == "") and self.default_path:
            path_str = self.default_path

        if not path_str:
            raise ValueError(f"file:* ref requires a path unless default_path is set. Got: {ref}")
        if not key:
            raise ValueError(f"file:* ref must include '#<KEY>' suffix. Got: {ref}")

        data = self._load_json(path_str)
        val = data.get(key)
        if val is None:
            return None
        if not isinstance(val, str):
            raise ValueError(f"Secret '{key}' must be a string in {path_str}")
        return val


@dataclass
class CompositeSecretProvider:
    providers: tuple[SecretProvider, ...]

    def get(self, ref: str) -> Optional[str]:
        # Route by the ref's scheme to the provider(s) that actually handle it. A provider that
        # structurally can't handle this scheme (e.g. FileSecretProvider given an ``env:`` ref) is SKIPPED —
        # never treated as "the failure" — so its "only supports file:*" message can't mask the real cause
        # (which is usually "the env var / file entry / config secret for this ref simply isn't set").
        scheme, _ = _split_ref(ref)                    # clean ValueError on a malformed ref
        handlers = [p for p in self.providers if getattr(p, "scheme", None) == scheme]
        # Back-compat: a custom provider that doesn't declare a ``scheme`` is still attempted (it may handle
        # any scheme). Built-in providers all declare one, so the default composite never reaches this.
        candidates = handlers + [p for p in self.providers if getattr(p, "scheme", None) is None]
        if not candidates:
            known = sorted(s for s in {getattr(p, "scheme", None) for p in self.providers} if s)
            raise ValueError(
                f"unknown secret scheme '{scheme}:' for ref '{ref}'. "
                f"Known schemes: {known or ['(none configured)']}."
            )
        errors: list[Exception] = []
        for p in candidates:
            try:
                v = p.get(ref)
            except Exception as e:                      # a matching provider that genuinely failed
                errors.append(e)
                continue
            if v is not None:
                return v
        if errors:
            raise errors[-1]
        # A provider for this scheme ran but produced nothing → the ref is well-formed, its source is empty.
        raise ValueError(
            f"secret ref '{ref}' did not resolve: the '{scheme}' source has no value for it "
            f"(is the environment variable / file entry / ConfigForge secret for it set?)."
        )


def default_secret_provider() -> SecretProvider:
    return CompositeSecretProvider(providers=(
        LiteralSecretProvider(),
        EnvSecretProvider(),
        FileSecretProvider(),
    ))