# app/validation/semver_key.py
"""Sort keys derived from semver (used for deterministic /resolve tie-breaks)."""
from __future__ import annotations

from typing import Tuple

from amendia_contracts.semver import parse_version


def version_desc_key(version: str) -> Tuple[int, int, int]:
    """Key that sorts higher versions first under ascending sort."""
    a, b, c = parse_version(version)
    return (-a, -b, -c)
