"""Unit tests for citation building and coverage measurement."""

from __future__ import annotations

from app.generation.citations import (
    build_citations,
    citation_coverage,
    extract_used_citation_indexes,
    make_quote,
)
from app.retrieval.retriever import RetrievedChunk


def _chunk(chunk_id: str, source: str, text: str, section: str = "Overview") -> RetrievedChunk:
    return RetrievedChunk(
        rank=1,
        chunk_id=chunk_id,
        text=text,
        source_file=source,
        title=source.replace(".md", "").title(),
        section=section,
        document_type="project",
        heading_path=f"{source} > {section}",
        technologies=["Node.js"],
        year=None,
        vector_score=0.9,
    )


def test_build_citations_deduplicates_and_preserves_order():
    chunks = [
        _chunk("c1", "devlens.md", "DevLens fetches repositories."),
        _chunk("c2", "enviromonitor.md", "EnviroMonitor computes AQI."),
        _chunk("c1", "devlens.md", "DevLens fetches repositories."),
    ]
    citations = build_citations(chunks)
    assert len(citations) == 2
    assert citations[0].source_file == "devlens.md"
    assert citations[1].source_file == "enviromonitor.md"


def test_citation_fields_are_complete():
    citations = build_citations([_chunk("c1", "devlens.md", "DevLens uses rate limiting.")])
    citation = citations[0]
    assert citation.source_file == "devlens.md"
    assert citation.document_type == "project"
    assert citation.section == "Overview"
    assert citation.chunk_id == "c1"
    assert "rate limiting" in citation.quote


def test_quote_is_short_and_complete_sentence():
    long_text = "First sentence here. " + "Filler words. " * 100
    quote = make_quote(long_text, max_length=80)
    assert len(quote) <= 81
    assert quote.startswith("First sentence here.")
    assert not quote.endswith("Filler")


def test_make_quote_handles_empty_text():
    assert make_quote("   ") == ""


def test_extract_used_citation_indexes():
    answer = "Backend work [1] and also [3] but not [99]."
    assert extract_used_citation_indexes(answer, total=4) == [1, 3]


def test_citation_coverage_partial():
    chunks = [_chunk("c1", "a.md", "A"), _chunk("c2", "b.md", "B")]
    coverage = citation_coverage("Answer cites only [1].", chunks)
    assert coverage.cited_indexes == [1]
    assert coverage.total_chunks == 2
    assert coverage.coverage == 0.5
    assert coverage.uncited_chunks == ["c2"]


def test_citation_coverage_full_and_empty():
    chunks = [_chunk("c1", "a.md", "A"), _chunk("c2", "b.md", "B")]
    full = citation_coverage("Uses [1] and [2].", chunks)
    assert full.coverage == 1.0
    assert full.uncited_chunks == []

    none = citation_coverage("No markers at all.", chunks)
    assert none.coverage == 0.0
    assert len(none.uncited_chunks) == 2


def test_citation_coverage_without_chunks():
    coverage = citation_coverage("Anything", [])
    assert coverage.coverage == 0.0
    assert coverage.total_chunks == 0
