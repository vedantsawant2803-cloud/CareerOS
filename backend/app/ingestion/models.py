"""Data models used across the ingestion pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Document(BaseModel):
    """A single loaded source file."""

    document_id: str
    source_file: str
    title: str
    document_type: str
    text: str
    content_hash: str
    metadata: dict[str, object] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A retrievable piece of a document with citation metadata."""

    chunk_id: str
    document_id: str
    text: str
    source_file: str
    document_type: str
    title: str
    section: str
    heading_path: str
    candidate: str = "Vedant Sawant"
    technologies: list[str] = Field(default_factory=list)
    year: int | None = None
    content_hash: str
    ingestion_timestamp: str = ""
    index: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)

    def payload(self) -> dict[str, object]:
        """Flatten the chunk into a Qdrant payload (text included for retrieval)."""
        return {
            "text": self.text,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_file": self.source_file,
            "document_type": self.document_type,
            "title": self.title,
            "section": self.section,
            "heading_path": self.heading_path,
            "candidate": self.candidate,
            "technologies": self.technologies,
            "year": self.year,
            "content_hash": self.content_hash,
            "ingestion_timestamp": self.ingestion_timestamp,
            "index": self.index,
            **self.metadata,
        }


class Section(BaseModel):
    """A heading-delimited section extracted from a Markdown document."""

    heading_path: str
    title: str
    level: int
    content: str


class IngestionResult(BaseModel):
    """Summary returned by the indexing pipeline and the ingest endpoint."""

    documents: int = 0
    chunks: int = 0
    indexed: int = 0
    skipped: int = 0
    collection: str = ""
    embedding_model: str = ""
    reranker_model: str = ""
    data_dir: str = ""
    reset: bool = False
    warnings: list[str] = Field(default_factory=list)

    def as_printable(self) -> str:
        """Human-readable summary used by ``scripts/seed_data.py``."""
        lines = [
            f"Documents read      : {self.documents}",
            f"Chunks created      : {self.chunks}",
            f"Chunks indexed      : {self.indexed}",
            f"Skipped             : {self.skipped}",
            f"Collection          : {self.collection}",
            f"Embedding model     : {self.embedding_model}",
            f"Reranker model      : {self.reranker_model}",
        ]
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"  - {warning}" for warning in self.warnings)
        return "\n".join(lines)
