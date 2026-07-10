from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Tuple


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

    def get(self, ref: str) -> Optional[str]:
        scheme, rest = _split_ref(ref)
        if scheme != "literal":
            raise ValueError(f"LiteralSecretProvider only supports literal:* refs. Got: {ref}")
        return rest  # the value itself IS the secret


class EnvSecretProvider:
    def get(self, ref: str) -> Optional[str]:
        scheme, rest = _split_ref(ref)
        if scheme != "env":
            raise ValueError(f"EnvSecretProvider only supports env:* refs. Got: {ref}")
        env_name = rest.strip()
        return os.getenv(env_name) if env_name else None


@dataclass
class FileSecretProvider:
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
        last_err: Optional[Exception] = None
        for p in self.providers:
            try:
                v = p.get(ref)
                if v is not None:
                    return v
            except Exception as e:
                last_err = e
        if last_err is not None:
            raise last_err
        return None


def default_secret_provider() -> SecretProvider:
    return CompositeSecretProvider(providers=(
        LiteralSecretProvider(),
        EnvSecretProvider(),
        FileSecretProvider(),
    ))