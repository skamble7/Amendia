# app/sample_data.py
"""Canned attachment files shipped as package data.

The stub IS the exception store, so it must serve attachment bytes itself.
Each catalog entry maps a stable ``attachment_id`` to a physical sample file,
its media type, and the (cached) sha256 of its real bytes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_SAMPLE_DIR = Path(__file__).parent / "sample_data"


@dataclass(frozen=True)
class SampleAttachment:
    attachment_id: str
    name: str
    media_type: str
    filename: str  # file under sample_data/

    @property
    def path(self) -> Path:
        return _SAMPLE_DIR / self.filename


# Stable catalog. ``att-1`` is the screenshot, ``att-2`` the analyst notes.
CATALOG: dict[str, SampleAttachment] = {
    "att-1": SampleAttachment("att-1", "beneficiary-screen.png", "image/png", "beneficiary-screen.png"),
    "att-2": SampleAttachment("att-2", "analyst-notes.txt", "text/plain", "analyst-notes.txt"),
}


@lru_cache(maxsize=None)
def read_bytes(attachment_id: str) -> bytes:
    return CATALOG[attachment_id].path.read_bytes()


@lru_cache(maxsize=None)
def sha256_of(attachment_id: str) -> str:
    return hashlib.sha256(read_bytes(attachment_id)).hexdigest()
