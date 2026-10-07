"""Structure-aware chunking.

Design decisions (see docs/architecture.md and docs/ingestion.md):

* Markdown headings define a section tree → the ``heading_path`` is preserved
  so citations can name the exact section a quote came from.
* Bullet lists are treated as atomic blocks so a bullet is never split across
  two chunks.
* Large sections are split with a sliding window that re-reads ``overlap``
  characters of the previous chunk for context continuity.
* Tiny fragments are merged into neighbours so we do not index single-line
  slivers that retrieve poorly.
"""

from __future__ import annotations

from app.ingestion.metadata import build_chunk
from app.ingestion.models import Chunk, Document, Section
from app.utils.hashing import sha256_text, stable_chunk_id
from app.utils.text import HEADING_RE, split_paragraphs


def split_markdown_sections(text: str, default_path: str = "Document") -> list[Section]:
    """Split Markdown into heading-delimited sections, preserving heading paths."""
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    buffer: list[str] = []
    path: list[str] = []

    def flush(current_path: list[str], level: int) -> None:
        content = "\n".join(buffer).strip()
        buffer.clear()
        if not current_path:
            return
        heading_path = " > ".join(current_path)
        sections.append(
            Section(
                heading_path=heading_path,
                title=current_path[-1],
                level=level,
                content=content,
            )
        )

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush(path, stack[-1][0] if stack else 1)
            level = len(match.group(1))
            heading = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            path = [item[1] for item in stack]
            continue
        buffer.append(line)

    if path:
        flush(path, stack[-1][0] if stack else 1)
    elif buffer:
        content = "\n".join(buffer).strip()
        if content:
            sections.append(
                Section(heading_path=default_path, title=default_path, level=1, content=content)
            )

    return sections


def _blocks_of(content: str) -> list[str]:
    """Paragraphs with bullet groups kept together."""
    return split_paragraphs(content)


def _split_oversized_block(block: str, size: int, overlap: int) -> list[str]:
    """Sliding-window split for a single block larger than ``size`` chars."""
    step = max(size - overlap, 200)
    pieces: list[str] = []
    start = 0
    while start < len(block):
        end = min(start + size, len(block))
        piece = block[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(block):
            break
        start += step
    return pieces


def _pack_blocks(blocks: list[str], size: int, overlap: int) -> list[str]:
    """Greedily pack blocks into chunk-sized groups without splitting bullets."""
    packed: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > size:
            if current:
                packed.append(current.strip())
                current = ""
            packed.extend(_split_oversized_block(block, size, overlap))
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= size:
            current = candidate
        else:
            if current:
                packed.append(current.strip())
            current = block
    if current:
        packed.append(current.strip())
    return [piece for piece in packed if piece]


def _apply_overlap(pieces: list[str], overlap: int) -> list[str]:
    """Prefix each piece (after the first) with the tail of the previous one."""
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    anchored: list[str] = [pieces[0]]
    for index in range(1, len(pieces)):
        previous_tail = pieces[index - 1][-overlap:].strip()
        # Avoid breaking mid-word when re-anchoring context.
        if " " in previous_tail:
            previous_tail = previous_tail.split(" ", 1)[1]
        if previous_tail and not pieces[index].startswith(previous_tail[:40]):
            pieces[index] = f"{previous_tail}\n{pieces[index]}"
        anchored.append(pieces[index])
    return anchored


def _merge_small(
    texts: list[str],
    min_length: int,
    size: int,
) -> list[str]:
    """Merge fragments below ``min_length`` into a neighbour when possible."""
    if not texts:
        return []
    merged: list[str] = []
    pending = ""
    for text in texts:
        candidate = f"{pending}\n\n{text}" if pending else text
        if len(candidate) <= size and (len(text) < min_length or len(pending) < min_length):
            pending = candidate
        else:
            if pending:
                merged.append(pending)
            pending = text
    if pending:
        # Never drop content: a final small fragment is appended to the last
        # chunk (or kept alone) instead of being discarded.
        if merged and len(pending) < min_length and len(merged[-1]) + len(pending) <= size * 2:
            merged[-1] = f"{merged[-1]}\n\n{pending}"
        else:
            merged.append(pending)
    return merged


def _merge_tiny_across_sections(
    chunks: list[Chunk],
    min_length: int,
    size: int,
) -> list[Chunk]:
    """Attach sub-minimum chunks to their predecessor (same document).

    Sections shorter than ``min_chunk_length`` otherwise become standalone
    slivers that retrieve poorly. The merged chunk keeps the predecessor's
    citation metadata and receives a recomputed deterministic chunk id.
    """
    if not chunks or min_length <= 0:
        return chunks
    from app.ingestion.metadata import detect_technologies, detect_year

    merged: list[Chunk] = []
    for chunk in chunks:
        if merged and len(chunk.text) < min_length:
            previous = merged[-1]
            combined = f"{previous.text}\n\n{chunk.text}"
            if len(combined) <= size:
                content_hash = sha256_text(combined)
                chunk_id = stable_chunk_id(
                    document_id=previous.document_id,
                    heading_path=previous.heading_path,
                    index=previous.index,
                    content_hash=content_hash,
                )
                updates: dict = {
                    "text": combined,
                    "content_hash": content_hash,
                    "chunk_id": chunk_id,
                    # Merged content changes the extracted metadata.
                    "technologies": detect_technologies(combined),
                    "year": detect_year(combined) or previous.year,
                }
                if chunk.section != previous.section:
                    # Keep citation attribution honest about both sections.
                    updates["heading_path"] = f"{previous.heading_path} | {chunk.heading_path}"
                    updates["section"] = f"{previous.section} + {chunk.section}"
                merged[-1] = previous.model_copy(update=updates)
                continue
        merged.append(chunk)
    return merged


def chunk_document(
    document: Document,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    min_chunk_length: int = 80,
    ingestion_timestamp: str = "",
) -> list[Chunk]:
    """Chunk one document into citation-ready pieces."""
    is_markdown = document.source_file.lower().endswith((".md", ".markdown"))
    sections = (
        split_markdown_sections(document.text, default_path=document.title)
        if is_markdown
        else [
            Section(
                heading_path=document.title,
                title=document.title,
                level=1,
                content=document.text,
            )
        ]
    )

    chunks: list[Chunk] = []
    global_index = 0
    for section in sections:
        if not section.content.strip():
            continue
        blocks = _blocks_of(section.content)
        packed = _pack_blocks(blocks, size=chunk_size, overlap=0)
        packed = _apply_overlap(packed, chunk_overlap)
        packed = _merge_small(packed, min_length=min_chunk_length, size=chunk_size)
        for text in packed:
            if not text.strip():
                continue
            chunks.append(
                build_chunk(
                    document=document,
                    section=section,
                    text=text.strip(),
                    index=global_index,
                    ingestion_timestamp=ingestion_timestamp,
                )
            )
            global_index += 1
    return _merge_tiny_across_sections(chunks, min_length=min_chunk_length, size=chunk_size)


def chunk_documents(
    documents: list[Document],
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
    min_chunk_length: int = 80,
    ingestion_timestamp: str = "",
) -> list[Chunk]:
    """Chunk every document, preserving document order."""
    all_chunks: list[Chunk] = []
    for document in documents:
        all_chunks.extend(
            chunk_document(
                document,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chunk_length=min_chunk_length,
                ingestion_timestamp=ingestion_timestamp,
            )
        )
    return all_chunks
