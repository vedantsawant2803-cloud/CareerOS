"""Integration tests for the ingestion pipeline (offline fakes)."""

from __future__ import annotations

import pytest
from app.ingestion.index_pipeline import IngestionError


def test_pipeline_indexes_sample_corpus(offline_pipeline, sample_corpus):
    pipeline, store = offline_pipeline
    result = pipeline.run(data_dir=sample_corpus)

    assert result.documents == 2
    assert result.chunks > 0
    assert result.indexed == result.chunks
    assert result.collection
    assert result.embedding_model
    assert result.reranker_model
    assert store.count() == result.chunks
    # The embedding dimension is detected from the provider, not hard-coded.
    assert store.dimension and store.dimension > 0


def test_pipeline_is_idempotent_on_rerun(offline_pipeline, sample_corpus):
    pipeline, store = offline_pipeline
    first = pipeline.run(data_dir=sample_corpus)
    second = pipeline.run(data_dir=sample_corpus)

    # Stale points for the same documents are deleted before upsert, so counts
    # must not grow across re-index runs.
    assert second.indexed == first.indexed
    assert store.count() == first.chunks


def test_pipeline_reset_rebuilds_collection(offline_pipeline, sample_corpus):
    pipeline, store = offline_pipeline
    pipeline.run(data_dir=sample_corpus)
    result = pipeline.run(data_dir=sample_corpus, reset=True)
    assert result.reset is True
    assert store.count() == result.chunks


def test_pipeline_missing_directory_raises(offline_pipeline, tmp_path):
    pipeline, _ = offline_pipeline
    with pytest.raises(IngestionError, match="Data directory not found"):
        pipeline.run(data_dir=tmp_path / "does-not-exist")


def test_pipeline_empty_directory_reports_warning(offline_pipeline, tmp_path):
    pipeline, store = offline_pipeline
    result = pipeline.run(data_dir=tmp_path)
    assert result.indexed == 0
    assert store.count() == 0
    assert any("No supported documents" in warning for warning in result.warnings)


def test_pipeline_skips_oversized_documents(offline_pipeline, tmp_path):
    long_doc = tmp_path / "huge.md"
    # Exceeds the default MAX_DOCUMENT_LENGTH of 100,000 characters.
    long_doc.write_text("# Huge\n\n" + ("filler content " * 8000), encoding="utf-8")
    pipeline, store = offline_pipeline
    result = pipeline.run(data_dir=tmp_path)
    assert result.skipped >= 1
    assert result.documents == 0
    assert store.count() == 0
    assert any("MAX_DOCUMENT_LENGTH" in warning for warning in result.warnings)


def test_pipeline_survives_unreadable_json_with_warning(offline_pipeline, tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "good.md").write_text(
        "# Good\n\n## Overview\n\nFine content here.\n", encoding="utf-8"
    )
    pipeline, store = offline_pipeline
    result = pipeline.run(data_dir=tmp_path)
    assert result.documents == 1
    assert result.indexed > 0
    assert any("not valid JSON" in warning for warning in result.warnings)


def test_chunk_payloads_include_citation_metadata(offline_pipeline, sample_corpus):
    pipeline, store = offline_pipeline
    pipeline.run(data_dir=sample_corpus)
    _, payload = store.points[0]
    for key in (
        "text",
        "chunk_id",
        "document_id",
        "source_file",
        "document_type",
        "title",
        "section",
        "heading_path",
        "candidate",
        "technologies",
        "content_hash",
        "ingestion_timestamp",
    ):
        assert key in payload, f"missing payload key: {key}"
