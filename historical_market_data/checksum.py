from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksum(text: str) -> str:
    match = re.search(r"\b([0-9a-fA-F]{64})\b", text)
    if not match:
        raise ValueError("official checksum does not contain SHA-256")
    return match.group(1).lower()


def verify_checksum(path: Path, expected: str) -> tuple[bool, str]:
    actual = sha256_file(path)
    return actual == expected.lower(), actual

