# Ingestion & Retrieval

How documents become citations: loaders → metadata → chunking → embeddings →
Qdrant, then how queries come back through retrieval, reranking, and filtering.

## Pipeline stages

```
data/sample_docs/*.md
   │  1. LOAD          .md .markdown .txt .json .pdf   (recursive, sorted)
   │  2. GUARD         skip docs > MAX_DOCUMENT_LENGTH (counted in `skipped`)
   │  3. METADATA      title, document_type, technologies, year, headings
   │  4. CHUNK         section-aware packing with overlap + tiny-chunk merging
   │  5. EMBED         EMBEDDING_MODEL, batched  → vector per chunk
   │  6. INDEX         upsert into QDRANT_COLLECTION with full payload
   ▼
Qdrant collection `career_os`
```

### 1. Loading (`app/ingestion/loaders.py`)

- Supported extensions: `.md`, `.markdown`, `.txt`, `.json`, `.pdf`
  (PDF requires the optional `pypdf` package).
- Files are discovered recursively and processed in sorted order for
  deterministic output.
- Markdown front matter (`key: value` block) is parsed and merged into metadata.
- A single unreadable file becomes a **warning**, never a failed run — one bad
  file cannot block indexing.

### 2. Size guard (`app/ingestion/index_pipeline.py`)

Documents longer than `MAX_DOCUMENT_LENGTH` (default 100 000 characters) are
skipped, reported in `warnings`, and counted in the response's `skipped` field.

### 3. Metadata (`app/ingestion/metadata.py`, `loaders.py`)

| Field | How it's derived |
| --- | --- |
| `document_type` | Filename shortcuts for the known corpus (`vedant_resume.md → resume`, `devlens.md → project`, `gdg_hackathon.md → hackathon`, `linkedin_summary.md → profile`, …), then filename heuristics (`hackathon`, `resume`/`cv`, `linkedin`/`profile`), then content heuristics (`## Technologies` + `## Overview/## Features` ⇒ `project`), falling back to `document`. |
| `title` | Front matter, first heading, or filename fallback. |
| `technologies` | Whole-word matching against a curated `KNOWN_TECHNOLOGIES` list (Node.js, Express, MySQL, Docker, React, …). Matching is case-insensitive and **word-boundary based**, so "AI" never matches inside "again". |
| `year` | Detected 4-digit years (1900–2100) in the text. |
| `heading_path` | H1/H2 hierarchy, e.g. `DevLens > Features`. |

### 4. Chunking (`app/ingestion/chunking.py`)

Section-aware, deterministic:

1. Documents are split into **sections** at heading boundaries (Markdown) or
   paragraph groups (plain text).
2. Blocks inside each section are packed to at most `CHUNK_SIZE` characters.
3. Consecutive chunks overlap by `CHUNK_OVERLAP` characters.
4. Under-filled chunks are merged forward within the section.
5. **Tiny-chunk merge:** any resulting chunk shorter than `MIN_CHUNK_LENGTH`
   is merged into its predecessor (if the combined size stays within
   `CHUNK_SIZE`). The merge recomputes `content_hash`, the deterministic
   `chunk_id`, `technologies`, `year`, and honestly combines the heading path
   (e.g. `DevLens | DevLens > Technologies`), so citations keep pointing at
   the right sections.

Every chunk receives a stable `chunk_id = sha256(document_id + heading_path +
index + content_hash)` — re-running ingestion with unchanged inputs reproduces
the same ids.

### 5–6. Embedding & indexing (`app/retrieval/embeddings.py`, `qdrant_store.py`)

- Model: `EMBEDDING_MODEL` (default `BAAI/bge-small-en-v1.5`), downloaded on
  first run by sentence-transformers.
- Vectors and chunk payloads are upserted in batches; each payload carries the
  complete citation metadata: `chunk_id`, `document_id`, `source_file`,
  `title`, `section`, `heading_path`, `document_type`, `technologies`, `year`,
  `text`, `content_hash`, `ingestion_timestamp`.
- `reset=true` (API) or `--reset` (script) drops and recreates the collection —
  required whenever the embedding model or chunking settings change.

## Running ingestion

```bash
# Script (local)
python scripts/seed_data.py
python scripts/seed_data.py --data-dir my_docs --reset --collection my_collection

# Script (inside Docker)
docker compose exec backend python scripts/seed_data.py

# API
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"data_dir": "data/sample_docs", "reset": true}'
```

`data_dir` must be a relative path inside the workspace — absolute paths,
drive letters, and `..` are rejected with a `422` validation error (path
traversal guard).

## Retrieval (`app/retrieval/`)

For each query:

1. **Embed** the query with the same model used at indexing time.
2. **Vector search** for `TOP_K_RETRIEVAL` candidates. Exact-match filters
   (`document_type`, `technology`, `year`) are **pushed down to Qdrant**:

   | Filter | Where applied | Notes |
   | --- | --- | --- |
   | `document_type` | Qdrant (exact, lowercased) | e.g. only `hackathon`. |
   | `technology` | Qdrant (exact against `technologies` list) | Canonical name, e.g. `MySQL`. |
   | `year` | Qdrant (exact integer) | 1900–2100. |
   | `project` | In-process, after scoring | Slugified comparison against `title`, `source_file`, and `heading_path`, so `DevLens`, `devlens`, and `devlens.md` all match. |

3. **Keyword boost:** add `KEYWORD_BOOST × word-overlap` to vector scores so
   exact-term questions (technology names, project names) rank reliably.
4. **Rerank (optional):** when `ENABLE_RERANKER=true` and the cross-encoder
   model is available, re-score the top candidates and keep the best
   `TOP_N_RERANKED`. If the reranker is disabled or unavailable, a warning is
   attached and vector scores are used as-is.
5. **Post-filter:** optional project filter and the final top-N cut.

### Retrieval health without models/Qdrant

The store, embedder, and reranker are behind small interfaces. The test suite
substitutes in-memory fakes, which is why `pytest tests` runs fully offline.
In production, if Qdrant or the LLM is unreachable, callers get an explicit
error (health endpoint) or a degraded-but-honest response (query endpoint) —
never silent fabrication.

## The sample corpus

`data/sample_docs/` contains the seven source documents (one résumé, three
project case studies, two hackathon entries, one profile summary). They are
the **single source of truth** for every answer: the API does not invent facts
outside this corpus, and each claim in an answer maps back to a citation card
with `source_file` + `section` + `quote`.
