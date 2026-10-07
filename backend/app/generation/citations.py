"""Citation construction.

Every factual answer must be traceable: a citation carries the source file,
document type, title, section, a stable chunk id, and a short supporting quote
copied verbatim from the retrieved chunk.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.retrieval.retriever import RetrievedChunk
from app.utils.text import first_sentence

QUOTE_MAX_LENGTH = 240


class Citation(BaseModel):
    """A single source reference attached to an answer."""

    source_file: str
    document_type: str
    title: str
    section: str
    chunk_id: str
    quote: str


def make_quote(text: str, max_length: int = QUOTE_MAX_LENGTH) -> str:
    """Short, verbatim-ish excerpt suitable for a citation card."""
    return first_sentence(text, max_length=max_length)


def build_citations(chunks: list[RetrievedChunk]) -> list[Citation]:
    """Build deduplicated citations from retrieved chunks (retrieval order)."""
    citations: list[Citation] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        citations.append(
            Citation(
                source_file=chunk.source_file,
                document_type=chunk.document_type,
                title=chunk.title,
                section=chunk.section,
                chunk_id=chunk.chunk_id,
                quote=make_quote(chunk.text),
            )
        )
    return citations


def extract_used_citation_indexes(answer: str, total: int) -> list[int]:
    """Parse ``[n]`` markers from an answer to measure citation coverage."""
    import re

    found: set[int] = set()
    for match in re.finditer(r"\[(\d{1,2})\]", answer):
        index = int(match.group(1))
        if 1 <= index <= total:
            found.add(index)
    return sorted(found)


class CitationCoverage(BaseModel):
    """Result of measuring how well an answer cites its sources."""

    cited_indexes: list[int] = Field(default_factory=list)
    total_chunks: int = 0
    coverage: float = 0.0
    uncited_chunks: list[str] = Field(default_factory=list)


def citation_coverage(answer: str, chunks: list[RetrievedChunk]) -> CitationCoverage:
    """Fraction of retrieved chunks referenced by ``[n]`` markers in the answer."""
    if not chunks:
        return CitationCoverage(cited_indexes=[], total_chunks=0, coverage=0.0)
    used = extract_used_citation_indexes(answer, total=len(chunks))
    coverage = len(used) / len(chunks)
    uncited = [
        chunks[index - 1].chunk_id for index in range(1, len(chunks) + 1) if index not in used
    ]
    return CitationCoverage(
        cited_indexes=used,
        total_chunks=len(chunks),
        coverage=round(coverage, 3),
        uncited_chunks=uncited,
    )
