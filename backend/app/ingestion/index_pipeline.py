"""The indexing pipeline: load → chunk → embed → upsert (with safe re-index)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.ingestion.chunking import chunk_documents
from app.ingestion.loaders import load_documents
from app.ingestion.metadata import utc_timestamp
from app.ingestion.models import IngestionResult
from app.retrieval.embeddings import EmbeddingProvider, EmbeddingUnavailableError
from app.retrieval.qdrant_store import QdrantStore, QdrantStoreError

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32


class IngestionError(RuntimeError):
    """Raised when indexing cannot complete (safe, user-facing messages)."""


class IndexPipeline:
    """Runs the full ingestion pipeline against the vector store."""

    def __init__(self, settings: Settings, embedder: EmbeddingProvider, store: QdrantStore) -> None:
        self.settings = settings
        self.embedder = embedder
        self.store = store

    def run(self, data_dir: str | Path | None = None, reset: bool = False) -> IngestionResult:
        """Index every supported document under ``data_dir``.

        ``reset=True`` drops the collection first (full rebuild). Regardless of
        ``reset``, points belonging to documents being re-indexed are removed
        before upsert, so re-runs never leave stale chunks behind.
        """
        target_dir = Path(data_dir or self.settings.data_dir)
        warnings: list[str] = []

        try:
            documents, load_warnings = load_documents(target_dir)
        except FileNotFoundError as exc:
            raise IngestionError(str(exc)) from exc
        warnings.extend(load_warnings)

        # Respect the configured document size limit.
        kept_documents = []
        skipped_documents = 0
        for document in documents:
            if len(document.text) > self.settings.max_document_length:
                warnings.append(
                    f"Skipped {document.source_file}: exceeds MAX_DOCUMENT_LENGTH "
                    f"({len(document.text)} > {self.settings.max_document_length})"
                )
                skipped_documents += 1
                continue
            kept_documents.append(document)
        documents = kept_documents

        chunks = chunk_documents(
            documents,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            min_chunk_length=self.settings.min_chunk_length,
            ingestion_timestamp=utc_timestamp(),
        )

        result = IngestionResult(
            documents=len(documents),
            chunks=len(chunks),
            indexed=0,
            skipped=skipped_documents,
            collection=self.settings.qdrant_collection,
            embedding_model=self.settings.embedding_model,
            reranker_model=self.settings.reranker_model,
            data_dir=str(target_dir),
            reset=reset,
            warnings=warnings,
        )

        if not documents or not chunks:
            result.warnings.append("Nothing to index: no documents or no chunks produced.")
            return result

        # --- Embeddings ----------------------------------------------------
        try:
            dimension = self.embedder.dimension
            vectors: list[list[float]] = []
            for start in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[start : start + EMBED_BATCH_SIZE]
                vectors.extend(self.embedder.embed_documents([chunk.text for chunk in batch]))
        except EmbeddingUnavailableError as exc:
            raise IngestionError(str(exc)) from exc

        if len(vectors) != len(chunks):  # pragma: no cover - defensive
            raise IngestionError("Embedding count did not match chunk count; aborting.")

        # --- Vector store ---------------------------------------------------
        try:
            if reset:
                self.store.reset()
            self.store.ensure_collection(dimension)
            # Safe re-indexing: drop stale points for these documents first.
            self.store.delete_document_ids([document.document_id for document in documents])
            indexed = self.store.upsert(chunks, vectors)
        except QdrantStoreError as exc:
            raise IngestionError(str(exc)) from exc

        result.indexed = indexed
        logger.info(
            "Indexed %s chunks from %s documents into '%s'",
            result.indexed,
            result.documents,
            result.collection,
        )
        return result
