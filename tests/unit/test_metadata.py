"""Unit tests for metadata extraction (technologies, years, chunk fields)."""

from __future__ import annotations

from app.ingestion.loaders import detect_document_type, extract_title, load_file
from app.ingestion.metadata import (
    build_chunk,
    describe_document,
    detect_technologies,
    detect_year,
)
from app.ingestion.models import Document, Section
from app.utils.hashing import sha256_text, stable_document_id


def _doc(text: str = "Body", source_file: str = "devlens.md") -> Document:
    return Document(
        document_id=stable_document_id(source_file),
        source_file=source_file,
        title="DevLens",
        document_type="project",
        text=text,
        content_hash=sha256_text(text),
    )


def test_detect_technologies_prefers_longest_match():
    techs = detect_technologies("Built with React Native and Node.js via Express.js")
    assert "React Native" in techs
    assert "Node.js" in techs
    assert "Express.js" in techs
    # "React" alone must not be double-counted when "React Native" matched.
    assert techs.count("React") == 0


def test_detect_technologies_deduplicates_and_keeps_order():
    techs = detect_technologies("Uses MySQL and MySQL again with Docker")
    assert techs == ["MySQL", "Docker"]


def test_detect_technologies_handles_github_prefix():
    techs = detect_technologies("Fetched via the GitHub REST API using Git")
    assert "GitHub REST API" in techs
    assert "Git" in techs


def test_detect_year_returns_first_plausible_year():
    assert detect_year("Hackathon in 2025 and stuff") == 2025
    assert detect_year("no years here") is None


def test_build_chunk_populates_citation_fields():
    document = _doc("DevLens implements rate limiting with Node.js in 2025.")
    section = Section(
        heading_path="DevLens > Features",
        title="Features",
        level=2,
        content=document.text,
    )
    chunk = build_chunk(
        document=document, section=section, text=document.text, index=0, ingestion_timestamp="t"
    )
    assert chunk.source_file == "devlens.md"
    assert chunk.document_type == "project"
    assert chunk.section == "Features"
    assert chunk.heading_path == "DevLens > Features"
    assert chunk.candidate == "Vedant Sawant"
    assert "Node.js" in chunk.technologies
    assert chunk.year == 2025
    assert chunk.content_hash
    assert chunk.ingestion_timestamp == "t"
    assert chunk.payload()["text"] == document.text


def test_chunk_ids_stable_across_calls():
    section = Section(heading_path="A", title="A", level=2, content="content")
    first = build_chunk(_doc(), section, "content", 0, "t")
    second = build_chunk(_doc(), section, "content", 0, "t")
    assert first.chunk_id == second.chunk_id


def test_describe_document_shape():
    described = describe_document(_doc("Uses MySQL in 2026"))
    assert described["source_file"] == "devlens.md"
    assert described["document_type"] == "project"
    assert "MySQL" in described["technologies"]
    assert 2026 in described["years"]


def test_extract_title_falls_back_gracefully():
    assert extract_title("# Real Heading\nbody", "fallback") == "Real Heading"
    assert extract_title("plain body text", "fallback") == "plain body text"
    assert extract_title("", "fallback") == "fallback"


def test_detect_document_type_from_known_names_and_heuristics():
    assert detect_document_type("vedant_resume.md", "", {}) == "resume"
    assert detect_document_type("gdg_hackathon.md", "", {}) == "hackathon"
    assert detect_document_type("custom.md", "", {"document_type": "case-study"}) == "case-study"
    body = "## Overview\nx\n## Technologies\ny"
    assert detect_document_type("anything.md", body, {}) == "project"
    assert detect_document_type("random.md", "just text", {}) == "document"


def test_load_file_json(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(
        '{"title": "JSON Doc", "content": "Backend work with Express."}',
        encoding="utf-8",
    )
    document = load_file(path, root=tmp_path)
    assert document is not None
    assert document.title == "JSON Doc"
    assert "Express" in document.text
    assert document.document_id == stable_document_id("notes.json")


def test_load_file_rejects_path_without_supporting_extension(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG")
    assert load_file(path, root=tmp_path) is None
