"""Content hashing and deterministic ID helpers.

Deterministic IDs are what make re-indexing safe: the same file always maps to
the same ``document_id``, so a re-run can delete stale points for that document
before upserting the new version.
"""

from __future__ import annotations

import hashlib


def sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of whitespace-normalized text."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def stable_document_id(source_file: str) -> str:
    """Document ID derived only from the source path (stable across edits)."""
    normalized = source_file.replace("\\", "/").strip().lower()
    return hashlib.sha256(f"doc::{normalized}".encode()).hexdigest()[:24]


def stable_chunk_id(document_id: str, heading_path: str, index: int, content_hash: str) -> str:
    """Chunk ID derived from position + content (changes only when content moves)."""
    key = f"chunk::{document_id}::{heading_path}::{index}::{content_hash[:16]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def short_hash(*parts: object, length: int = 8) -> str:
    """Short deterministic hash for arbitrary parts (used for cache keys)."""
    joined = "::".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]
