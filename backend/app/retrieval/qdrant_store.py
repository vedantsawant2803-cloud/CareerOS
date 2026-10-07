"""Qdrant vector store wrapper.

Responsibilities:

* Create the collection with the **detected** embedding dimension.
* Upsert chunks in batches and delete stale points on re-index (safe
  re-indexing keyed by ``document_id``).
* Translate metadata filters into Qdrant filters.
* Fail with actionable messages when Qdrant is unreachable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.ingestion.models import Chunk

logger = logging.getLogger(__name__)


class QdrantStoreError(RuntimeError):
    """Raised for vector-store level failures with user-safe messages."""


@dataclass
class ScoredPoint:
    """Minimal scored-point representation decoupled from the Qdrant SDK."""

    id: str
    score: float
    payload: dict


class QdrantStore:
    """Thin, testable wrapper over :class:`qdrant_client.QdrantClient`."""

    def __init__(
        self,
        url: str,
        collection: str,
        api_key: str | None = None,
        timeout: int = 10,
    ) -> None:
        self.url = url
        self.collection = collection
        self.api_key = api_key or None
        self.timeout = timeout
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key,
                timeout=self.timeout,
                prefer_grpc=False,
            )
        return self._client

    # ------------------------------------------------------------------
    def ping(self) -> bool:
        """True when Qdrant answers within the client timeout."""
        try:
            self.client.get_collections()
            return True
        except Exception as exc:  # noqa: BLE001 - any transport error = down
            logger.warning("Qdrant unreachable at %s: %s", self.url, exc)
            return False

    def collection_exists(self) -> bool:
        try:
            return bool(self.client.collection_exists(self.collection))
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(f"Could not check Qdrant collection: {exc}") from exc

    def ensure_collection(self, dimension: int) -> None:
        """Create the collection if missing; validate dimension if present."""
        try:
            if self.collection_exists():
                info = self.client.get_collection(self.collection)
                existing = getattr(info.config, "params", None)
                vectors = getattr(existing, "vectors", None)
                existing_dim = getattr(vectors, "size", None)
                if existing_dim and int(existing_dim) != int(dimension):
                    raise QdrantStoreError(
                        f"Collection '{self.collection}' has vector size {existing_dim} but the "
                        f"embedding model produces {dimension}. "
                        "Re-index with `python scripts/seed_data.py --reset`."
                    )
                return
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection '%s' (dim=%s)", self.collection, dimension)
        except QdrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(
                f"Could not prepare Qdrant collection at {self.url}: {exc}"
            ) from exc

    def reset(self) -> None:
        """Delete the collection entirely (full re-index)."""
        try:
            if self.collection_exists():
                self.client.delete_collection(self.collection)
                logger.info("Deleted Qdrant collection '%s'", self.collection)
        except QdrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(f"Could not reset collection: {exc}") from exc

    # ------------------------------------------------------------------
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]], batch_size: int = 64) -> int:
        """Upsert chunk/vector pairs; returns the number of points written."""
        if len(chunks) != len(vectors):
            raise QdrantStoreError("Chunk and vector counts do not match; refusing to upsert.")
        total = 0
        try:
            for start in range(0, len(chunks), batch_size):
                batch_chunks = chunks[start : start + batch_size]
                batch_vectors = vectors[start : start + batch_size]
                points = [
                    models.PointStruct(
                        id=index_point_id(chunk.chunk_id),
                        vector=vector,
                        payload=chunk.payload(),
                    )
                    for chunk, vector in zip(batch_chunks, batch_vectors, strict=True)
                ]
                self.client.upsert(collection_name=self.collection, points=points)
                total += len(points)
            return total
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(f"Upsert failed: {exc}") from exc

    def delete_document_ids(self, document_ids: list[str]) -> None:
        """Remove every point belonging to the given documents (re-index safety)."""
        if not document_ids:
            return
        try:
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchAny(any=document_ids),
                            )
                        ]
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(f"Could not delete stale points: {exc}") from exc

    def search(
        self,
        vector: list[float],
        limit: int,
        qdrant_filter: models.Filter | None = None,
    ) -> list[ScoredPoint]:
        """Dense vector search with optional metadata filter."""
        try:
            kwargs: dict = {
                "collection_name": self.collection,
                "query": vector,
                "limit": limit,
                "with_payload": True,
            }
            if qdrant_filter is not None:
                kwargs["query_filter"] = qdrant_filter
            result = self.client.query_points(**kwargs)
            points = getattr(result, "points", result) or []
            return [
                ScoredPoint(
                    id=str(point.id),
                    score=float(point.score),
                    payload=dict(point.payload or {}),
                )
                for point in points
            ]
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(
                f"Vector search failed at {self.url}: {exc}. "
                "Is Qdrant running and the collection indexed?"
            ) from exc

    def count(self) -> int:
        try:
            if not self.collection_exists():
                return 0
            info = self.client.count(self.collection, exact=True)
            return int(info.count)
        except QdrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QdrantStoreError(f"Could not count points: {exc}") from exc


def index_point_id(chunk_id: str) -> str:
    """Convert a hex chunk id into a UUID-derived integer Qdrant point id.

    Qdrant accepts unsigned integers or UUIDs as point ids. Mapping the
    deterministic chunk id through SHA-256 keeps upserts idempotent.
    """
    import hashlib

    digest = hashlib.sha256(chunk_id.encode("utf-8")).hexdigest()
    return str(int(digest[:32], 16) % (2**63 - 1))
