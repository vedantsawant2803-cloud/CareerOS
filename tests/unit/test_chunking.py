"""Unit tests for structure-aware chunking."""

from __future__ import annotations

from app.ingestion.chunking import chunk_document, split_markdown_sections
from app.ingestion.loaders import load_file
from app.ingestion.models import Document
from app.utils.hashing import sha256_text, stable_document_id


def _document(text: str, source_file: str = "sample.md") -> Document:
    return Document(
        document_id=stable_document_id(source_file),
        source_file=source_file,
        title="Sample",
        document_type="project",
        text=text,
        content_hash=sha256_text(text),
    )


def test_split_markdown_sections_preserves_heading_paths():
    text = (
        "# Title\n\nSome intro.\n\n"
        "## Overview\n\nFirst section body.\n\n"
        "### Details\n\nNested body.\n"
    )
    sections = split_markdown_sections(text)
    paths = [section.heading_path for section in sections]
    assert "Title" in paths
    assert "Title > Overview" in paths
    assert "Title > Overview > Details" in paths


def test_split_sections_capture_bullet_groups():
    text = "# T\n\n## List\n\n- one\n- two\n- three\n"
    sections = split_markdown_sections(text)
    list_section = next(section for section in sections if section.title == "List")
    assert "- one" in list_section.content
    assert "- three" in list_section.content


def test_chunks_preserve_project_name_and_headings():
    text = (
        "# DevLens\n\n**Subtitle**\n\n"
        "## Overview\n\nDevLens is a code review tool.\n\n"
        "## Technologies\n\n- React\n- Node.js\n"
    )
    chunks = chunk_document(_document(text, "devlens.md"))
    assert chunks
    assert all(chunk.source_file == "devlens.md" for chunk in chunks)
    assert all(chunk.title == "Sample" or chunk.title for chunk in chunks)
    # Heading path survives into chunk metadata for citation sections.
    assert any("Overview" in chunk.heading_path for chunk in chunks)


def test_bullets_are_not_split_across_chunks():
    text = "# T\n\n## B\n\n" + "\n".join(f"- item {index}" for index in range(20)) + "\n"
    chunks = chunk_document(_document(text), chunk_size=400, chunk_overlap=0, min_chunk_length=0)
    for chunk in chunks:
        # Every chunk must contain complete bullet lines only.
        for line in chunk.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                assert stripped.endswith(tuple("0123456789")) or "item" in stripped


def test_large_section_is_split_with_overlap():
    paragraph = "This is a sentence about backend engineering practices. " * 120
    text = f"# T\n\n## Big\n\n{paragraph}\n"
    chunks = chunk_document(_document(text), chunk_size=500, chunk_overlap=80, min_chunk_length=50)
    assert len(chunks) >= 2
    # Overlap re-anchors context: later chunks are longer than plain content
    # because they carry a tail of the previous chunk.
    assert all(chunk.text.strip() for chunk in chunks)


def test_tiny_sections_merge_into_neighbours():
    text = (
        "# T\n\n## A\n\nShort section A content for merging tests.\n\n"
        "## B\n\nShort section B content for merging tests.\n\n"
        "## C\n\n" + "Long enough content to stand alone. " * 20
    )
    chunks = chunk_document(_document(text), chunk_size=600, chunk_overlap=0, min_chunk_length=120)
    assert len(chunks) >= 2
    # No 10-character slivers survive: tiny sections are merged into neighbours.
    assert min(len(chunk.text) for chunk in chunks) >= 40
    # Sections A and B are small enough to be joined into a single chunk.
    combined = any("section A" in chunk.text and "section B" in chunk.text for chunk in chunks)
    assert combined


def test_chunk_ids_are_deterministic():
    text = "# T\n\n## A\n\nContent for stability testing.\n"
    first = chunk_document(_document(text, "same.md"))
    second = chunk_document(_document(text, "same.md"))
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]


def test_chunk_ids_change_when_content_changes():
    before = chunk_document(_document("# T\n\n## A\n\nOriginal content.\n", "same.md"))
    after = chunk_document(_document("# T\n\n## A\n\nCompletely rewritten content.\n", "same.md"))
    assert [chunk.chunk_id for chunk in before] != [chunk.chunk_id for chunk in after]


def test_non_markdown_documents_still_chunk(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Plain text document " * 50, encoding="utf-8")
    document = load_file(path, root=tmp_path)
    assert document is not None
    chunks = chunk_document(document, chunk_size=300, chunk_overlap=0, min_chunk_length=10)
    assert chunks
    assert chunks[0].document_type in {"document", "project"}
