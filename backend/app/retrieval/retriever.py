"""Query-time retrieval orchestration.

Flow: embed query → dense search (+ push-down filters) → optional keyword
boosting → optional cross-encoder reranking → project post-filter → top-N cut
→ confidence estimate.

Failures degrade gracefully: reranker problems become warnings, not errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings
from app.retrieval import filters as filter_utils
from app.retrieval.embeddings import EmbeddingProvider, EmbeddingUnavailableError
from app.retrieval.qdrant_store import QdrantStore, QdrantStoreError, ScoredPoint
from app.retrieval.reranker import CrossEncoderReranker, RerankerUnavailableError
from app.utils.text import keyword_overlap_score

logger = logging.getLogger(__name__)

# Documented score→confidence heuristics (see docs/evaluation.md).
RERANK_HIGH = 3.0
RERANK_MEDIUM = 0.5
VECTOR_HIGH = 0.6
VECTOR_MEDIUM = 0.4


class RetrievalError(RuntimeError):
    """Raised when retrieval cannot run (embeddings or store unavailable)."""


@dataclass
class RetrievedChunk:
    """One retrieved chunk with both vector and rerank scores."""

    rank: int
    chunk_id: str
    text: str
    source_file: str
    title: str
    section: str
    document_type: str
    heading_path: str
    technologies: list[str] = field(default_factory=list)
    year: int | None = None
    vector_score: float = 0.0
    rerank_score: float | None = None
    document_id: str = ""

    @classmethod
    def from_point(cls, point: ScoredPoint, rank: int) -> RetrievedChunk:
        payload = point.payload
        return cls(
            rank=rank,
            chunk_id=str(payload.get("chunk_id", point.id)),
            text=str(payload.get("text") or payload.get("content") or ""),
            source_file=str(payload.get("source_file", "")),
            title=str(payload.get("title", "")),
            section=str(payload.get("section", "")),
            document_type=str(payload.get("document_type", "")),
            heading_path=str(payload.get("heading_path", "")),
            technologies=list(payload.get("technologies") or []),
            year=payload.get("year"),
            vector_score=point.score,
            document_id=str(payload.get("document_id", "")),
        )


@dataclass
class RetrievalResult:
    """Retrieved chunks plus internal diagnostics for the response metadata."""

    chunks: list[RetrievedChunk]
    warnings: list[str] = field(default_factory=list)
    searched: int = 0
    confidence: str = "none"
    reranked: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.chunks


class Retriever:
    """Executes the full retrieval pipeline for a single query."""

    def __init__(
        self,
        settings: Settings,
        embedder: EmbeddingProvider,
        store: QdrantStore,
        reranker: CrossEncoderReranker | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.reranker = reranker

    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        project: str | None = None,
        document_type: str | None = None,
        technology: str | None = None,
        year: int | None = None,
        top_k: int | None = None,
        top_n: int | None = None,
    ) -> RetrievalResult:
        top_k = top_k or self.settings.top_k_retrieval
        # Over-fetch a little when a project filter will run post-hoc.
        search_limit = top_k * 2 if project else top_k
        warnings: list[str] = []

        try:
            vector = self.embedder.embed_query(query)
        except EmbeddingUnavailableError as exc:
            raise RetrievalError(str(exc)) from exc

        qdrant_filter = filter_utils.build_qdrant_filter(
            project=project,
            document_type=document_type,
            technology=technology,
            year=year,
        )

        try:
            points = self.store.search(vector, limit=search_limit, qdrant_filter=qdrant_filter)
        except QdrantStoreError as exc:
            raise RetrievalError(str(exc)) from exc

        if not points:
            return RetrievalResult(chunks=[], warnings=warnings, searched=0, confidence="none")

        # --- optional keyword boosting -------------------------------------
        boosted = list(points)
        if self.settings.keyword_boost > 0:
            boosted.sort(
                key=lambda point: (
                    point.score
                    + self.settings.keyword_boost
                    * keyword_overlap_score(query, str(point.payload.get("text", "")))
                ),
                reverse=True,
            )

        # --- optional cross-encoder reranking ------------------------------
        reranked_scores: list[float] | None = None
        reranker = self.reranker
        if reranker is not None and reranker.available:
            try:
                texts = [str(point.payload.get("text", "")) for point in boosted]
                reranked_scores = reranker.score(query, texts)
            except RerankerUnavailableError as exc:
                warnings.append(f"Reranker unavailable, using vector scores: {exc}")
                logger.warning("Reranker fallback: %s", exc)
        elif reranker is not None and not reranker.enabled:
            warnings.append("Reranking disabled by configuration (ENABLE_RERANKER=false).")
        else:
            warnings.append("Reranker model or library unavailable; using vector scores.")

        if reranked_scores is not None:
            combined = list(zip(boosted, reranked_scores, strict=False))
            combined.sort(key=lambda item: item[1], reverse=True)
            boosted = [point for point, _ in combined]
            rerank_by_chunk = {
                str(point.payload.get("chunk_id", point.id)): score for (point, score) in combined
            }
        else:
            rerank_by_chunk = {}

        # --- project post-filter + top-N cut --------------------------------
        kept = filter_utils.apply_project_filter(boosted, project)
        limit = top_n or self.settings.top_n_reranked
        kept = kept[:limit]

        chunks: list[RetrievedChunk] = []
        for index, point in enumerate(kept, start=1):
            chunk = RetrievedChunk.from_point(point, rank=index)
            chunk_id = str(point.payload.get("chunk_id", point.id))
            if chunk_id in rerank_by_chunk:
                chunk.rerank_score = round(float(rerank_by_chunk[chunk_id]), 4)
            chunks.append(chunk)

        confidence = self.estimate_confidence(chunks, reranked=bool(rerank_by_chunk))
        if not chunks:
            warnings.append("No chunks matched the requested filters.")
        return RetrievalResult(
            chunks=chunks,
            warnings=warnings,
            searched=len(points),
            confidence=confidence,
            reranked=bool(rerank_by_chunk),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def estimate_confidence(chunks: list[RetrievedChunk], reranked: bool) -> str:
        """Heuristic confidence label: high / medium / low / none."""
        if not chunks:
            return "none"
        if reranked and chunks[0].rerank_score is not None:
            score = chunks[0].rerank_score
            if score >= RERANK_HIGH:
                return "high"
            if score >= RERANK_MEDIUM:
                return "medium"
            return "low"
        score = chunks[0].vector_score
        if score >= VECTOR_HIGH:
            return "high"
        if score >= VECTOR_MEDIUM:
            return "medium"
        return "low"
