"""Integration tests for the Qdrant store wrapper (client fully mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.ingestion.models import Chunk
from app.retrieval.qdrant_store import (
    QdrantStore,
    QdrantStoreError,
    ScoredPoint,
    index_point_id,
)
from qdrant_client import models


def _store() -> QdrantStore:
    store = QdrantStore(url="http://qdrant.test:6333", collection="test_collection")
    store._client = MagicMock()
    return store


def _chunk(chunk_id: str = "abc123", document_id: str = "doc1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text="Backend work with Node.js",
        source_file="devlens.md",
        document_type="project",
        title="DevLens",
        section="Overview",
        heading_path="DevLens > Overview",
        technologies=["Node.js"],
        year=2025,
        content_hash="hash",
        ingestion_timestamp="t",
        index=0,
    )


def test_index_point_id_is_deterministic_integer():
    first = index_point_id("chunk-a")
    second = index_point_id("chunk-a")
    assert first == second
    assert first.isdigit()
    assert index_point_id("chunk-b") != first


def test_ensure_collection_creates_when_missing():
    store = _store()
    store.client.collection_exists.return_value = False
    store.ensure_collection(dimension=384)
    store.client.create_collection.assert_called_once()
    kwargs = store.client.create_collection.call_args.kwargs
    assert kwargs["collection_name"] == "test_collection"
    assert kwargs["vectors_config"].size == 384
    assert kwargs["vectors_config"].distance == models.Distance.COSINE


def test_ensure_collection_validates_existing_dimension():
    store = _store()
    store.client.collection_exists.return_value = True
    store.client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=384)))
    )
    store.ensure_collection(dimension=384)  # matching → no create
    store.client.create_collection.assert_not_called()

    with pytest.raises(QdrantStoreError, match="vector size"):
        store.ensure_collection(dimension=768)


def test_ensure_collection_reports_connection_failures():
    store = _store()
    store.client.collection_exists.side_effect = ConnectionError("refused")
    with pytest.raises(QdrantStoreError, match="Could not check Qdrant collection"):
        store.ensure_collection(dimension=8)


def test_upsert_writes_points_with_payloads():
    store = _store()
    written = store.upsert([_chunk()], [[0.1, 0.2, 0.3]])
    assert written == 1
    kwargs = store.client.upsert.call_args.kwargs
    assert kwargs["collection_name"] == "test_collection"
    point = kwargs["points"][0]
    assert point.payload["text"] == "Backend work with Node.js"
    assert point.payload["source_file"] == "devlens.md"
    assert point.payload["technologies"] == ["Node.js"]
    assert point.vector == [0.1, 0.2, 0.3]


def test_upsert_rejects_mismatched_lengths():
    store = _store()
    with pytest.raises(QdrantStoreError, match="do not match"):
        store.upsert([_chunk()], [])
    store.client.upsert.assert_not_called()


def test_delete_document_ids_builds_document_filter():
    store = _store()
    store.delete_document_ids(["doc1", "doc2"])
    kwargs = store.client.delete.call_args.kwargs
    selector = kwargs["points_selector"]
    condition = selector.filter.must[0]
    assert condition.key == "document_id"
    assert list(condition.match.any) == ["doc1", "doc2"]


def test_delete_document_ids_noop_on_empty_list():
    store = _store()
    store.delete_document_ids([])
    store.client.delete.assert_not_called()


def test_search_maps_payloads_and_scores():
    store = _store()
    store.client.query_points.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(id="1", score=0.91, payload={"chunk_id": "c1", "text": "hello"}),
            SimpleNamespace(id="2", score=0.72, payload={"chunk_id": "c2", "text": "world"}),
        ]
    )
    results = store.search([0.1, 0.2], limit=5)
    assert len(results) == 2
    assert isinstance(results[0], ScoredPoint)
    assert results[0].score == 0.91
    assert results[0].payload["chunk_id"] == "c1"
    # Score order is preserved from the store.
    assert results[1].score < results[0].score


def test_search_passes_filter_through():
    store = _store()
    store.client.query_points.return_value = SimpleNamespace(points=[])
    qdrant_filter = models.Filter(
        must=[models.FieldCondition(key="year", match=models.MatchValue(value=2025))]
    )
    store.search([0.1], limit=3, qdrant_filter=qdrant_filter)
    kwargs = store.client.query_points.call_args.kwargs
    assert kwargs["query_filter"] is qdrant_filter
    assert kwargs["limit"] == 3


def test_search_raises_store_error_on_failure():
    store = _store()
    store.client.query_points.side_effect = ConnectionError("down")
    with pytest.raises(QdrantStoreError, match="Vector search failed"):
        store.search([0.1], limit=3)


def test_ping_reflects_connectivity():
    store = _store()
    store.client.get_collections.return_value = []
    assert store.ping() is True
    store.client.get_collections.side_effect = ConnectionError("down")
    assert store.ping() is False


def test_count_and_reset():
    store = _store()
    store.client.collection_exists.return_value = False
    assert store.count() == 0

    store.client.collection_exists.return_value = True
    store.client.count.return_value = SimpleNamespace(count=42)
    assert store.count() == 42

    store.reset()
    store.client.delete_collection.assert_called_once_with("test_collection")
