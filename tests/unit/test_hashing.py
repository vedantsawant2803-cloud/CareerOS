"""Unit tests for hashing and deterministic IDs."""

from __future__ import annotations

from app.utils.hashing import sha256_text, short_hash, stable_chunk_id, stable_document_id


def test_sha256_text_normalizes_whitespace():
    assert sha256_text("hello   world") == sha256_text("hello world")
    assert sha256_text("hello world") != sha256_text("hello worlds")


def test_sha256_text_is_hex_and_full_length():
    digest = sha256_text("career os")
    assert len(digest) == 64
    int(digest, 16)  # valid hex


def test_stable_document_id_independent_of_content():
    # Document IDs are keyed to the source path so re-indexing can delete
    # stale vectors even after the file content changes.
    before = stable_document_id("data/sample_docs/devlens.md")
    after = stable_document_id("data/sample_docs/devlens.md")
    assert before == after
    assert len(before) == 24


def test_stable_document_id_normalizes_separators_and_case():
    unix_style = stable_document_id("data/sample_docs/DevLens.md")
    windows_style = stable_document_id("data\\sample_docs\\devlens.md")
    assert unix_style == windows_style


def test_stable_document_id_differs_per_file():
    assert stable_document_id("devlens.md") != stable_document_id("enviromonitor.md")


def test_stable_chunk_id_depends_on_position_and_content():
    base = stable_chunk_id("doc123", "DevLens > Features", 0, "hash-a")
    assert base == stable_chunk_id("doc123", "DevLens > Features", 0, "hash-a")
    assert base != stable_chunk_id("doc123", "DevLens > Features", 1, "hash-a")
    assert base != stable_chunk_id("doc123", "DevLens > Features", 0, "hash-b")
    assert base != stable_chunk_id("doc123", "DevLens > Overview", 0, "hash-a")


def test_short_hash_deterministic_and_sized():
    assert short_hash("a", "b") == short_hash("a", "b")
    assert short_hash("a", "b") != short_hash("ab")
    assert len(short_hash("x", length=8)) == 8
