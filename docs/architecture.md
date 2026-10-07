# Architecture

CareerOS is a small, layered RAG system: a FastAPI backend does ingestion,
retrieval, and generation; a Streamlit frontend consumes the HTTP API; Qdrant
stores vectors; and any OpenAI-compatible LLM (Ollama by default) produces
answers. Everything is wired through an explicit **composition root** so the
same code runs in Docker, on bare metal, and in offline tests.

## High-level components

```
frontend/app.py  ──HTTP──►  backend/app (FastAPI)
                               │
              ┌────────────────┼─────────────────────┐
              ▼                ▼                     ▼
        IngestionService  CareerService        HealthService
              │                │                     │
              ▼                ▼                     │
      IndexPipeline       Retriever ◄── filters       │
              │                │                      │
              ▼                ▼                      │
        Embedder +        QdrantStore ────────► Qdrant
        Chunker                │
                               ▼
                        AnswerGenerator ──────► LLM (OpenAI-compatible)
                               │
                               ▼
                        citations + coverage
```

### Backend packages

| Package | Responsibility |
| --- | --- |
| `app/config.py` | Typed `Settings` (pydantic-settings) loaded from env/`.env`, with validators and a fail-fast `validate_environment()` (production guardrails). |
| `app/main.py` | `create_app(settings=None, container=None)` — the composition root that builds the container, configures logging, CORS, error handlers, and routers. |
| `app/dependencies.py` | `Container` (service registry), `require_api_key` dependency, settings accessor. |
| `app/api/` | `routes.py` (HTTP surface), `schemas.py` (request/response contract), `error_handlers.py` (uniform error envelope). |
| `app/ingestion/` | `loaders` (md/txt/json) → `metadata` (title, type, tech detection) → `chunking` → `index_pipeline` (embed + upsert into Qdrant). |
| `app/retrieval/` | `embeddings` (sentence-transformers, lazy import), `qdrant_store` (thin client wrapper), `filters` (metadata conditions), `retriever` (search → boost → optional rerank → top-N), `reranker` (cross-encoder, optional). |
| `app/generation/` | `prompts` (per-mode system prompts, `SUPPORTED_MODES`), `context_formatter` (numbered chunks), `citations` (extraction + coverage), `generator` (OpenAI-compatible chat client with offline fallback). |
| `app/services/` | `CareerService` (query answering, profile/projects parsing), `IngestionService`, `HealthService`. |
| `app/utils/` | Hashing (document/chunk ids), text helpers, timing. |

## Request lifecycle (POST /api/v1/query)

1. **Validation** — pydantic schema checks mode, query length
   (`MAX_QUERY_LENGTH`), and job-description requirements for `tailor_resume`
   and `skill_gap`. Failures return `422` with
   `{"detail": "...", "type": "validation_error"}`.
2. **API-key guard** — optional `X-API-Key` check on all `/api/v1` routes
   (`GET /health` stays open for orchestrators).
3. **Retrieval** — `Retriever` embeds the query, runs a filtered vector search
   (`TOP_K_RETRIEVAL`), applies a keyword boost, then an optional cross-encoder
   rerank (`ENABLE_RERANKER`) and cuts to `TOP_N_RERANKED`.
4. **Generation** — the formatter renders numbered chunks; the generator calls
   the configured OpenAI-compatible endpoint with a per-mode prompt. If the
   endpoint is unreachable, it returns a **grounded fallback** (retrieved
   evidence + citation markers), sets `used_llm=false`, and appends a warning —
   it never invents an answer.
5. **Citations** — citation cards are built from chunk metadata
   (`source_file`, `document_type`, `title`, `section`, `chunk_id`, `quote`);
   coverage = fraction of retrieved chunks referenced by `[n]` markers.
6. **Response** — `answer`, `mode`, `citations`, `metadata` (retrieval count,
   latency, confidence, warnings), and optionally `retrieved_chunks` debug view.

## Ingestion lifecycle (POST /api/v1/ingest or scripts/seed_data.py)

```
documents (.md/.txt/.json)
   → load + normalize (relative path safety checks)
   → size guard (MAX_DOCUMENT_LENGTH; oversized files are skipped + warned)
   → metadata (title, headings, document_type, technologies, year)
   → section-aware chunking (CHUNK_SIZE / CHUNK_OVERLAP / MIN_CHUNK_LENGTH)
   → embed (EMBEDDING_MODEL, batched)
   → upsert into QDRANT_COLLECTION (payload = full citation metadata)
```

See [`docs/ingestion.md`](ingestion.md) for the detailed rules.

## Key design decisions

**Explicit composition root + DI container.**
`create_app(settings=..., container=...)` lets tests inject fakes
(`FakeEmbedder`, `FakeStore`, `StubGenerator`) without monkeypatching, while
production code builds real clients. No hidden global state beyond a cached
`get_settings()`.

**Offline tests by design.**
Heavy dependencies (sentence-transformers, torch, pypdf) are imported lazily
inside the classes that need them, so `pytest tests` runs with no model
downloads, no Qdrant, and no LLM. The suite (98 tests) covers chunking,
metadata, hashing, citations, the store abstraction, the pipeline, and the HTTP
contract.

**Graceful degradation over hard failure.**
A missing LLM, a disabled reranker, or a Qdrant hiccup degrade the response
(with explicit `warnings`) instead of 500-ing — a portfolio demo should stay
inspectable when the network is imperfect.

**Citations as first-class output.**
Answers are only as good as their provenance: every chunk carries a stable
`chunk_id` (sha256-based), heading path, and source file so the UI can render
verifiable citation cards.

**Privacy by default.**
Contact information is excluded from responses unless
`SHOW_CONTACT_INFORMATION=true`; production settings validation actively
rejects unsafe combinations (wildcard CORS, debug endpoints, contact
exposure).

## Frontend

`frontend/app.py` is a Streamlit app with a sidebar radio for five pages:

| Page | Backend usage |
| --- | --- |
| Ask CareerOS | `POST /api/v1/query` (modes `qa`, `project_summary`) |
| Explore Projects | `GET /api/v1/projects` + filtered queries |
| Tailor for a Job | `POST /api/v1/query` mode `tailor_resume` / `skill_gap` with `job_description` |
| Interview Preparation | `POST /api/v1/query` mode `interview_prep` |
| About the System | `GET /health`, `GET /api/v1/config/status` (booleans only) |

The frontend reads `BACKEND_URL` from the environment —
`http://backend:8000` under Docker, `http://localhost:8000` for bare-metal runs.

## Deployment topology (docker-compose.yml)

| Service | Image / build | Exposed | Notes |
| --- | --- | --- | --- |
| `qdrant` | `qdrant/qdrant:v1.12.4` | 6333 | Named volume `qdrant_data`; TCP healthcheck. |
| `backend` | `./backend` | 8000 | `QDRANT_URL=http://qdrant:6333` forced; mounts `./data` and `./scripts`; healthcheck hits `/health`. |
| `frontend` | `./frontend` | 8501 | `BACKEND_URL=http://backend:8000`; starts after backend is healthy. |

Rules of thumb baked into the compose files:

- **Service names, never localhost**, for container-to-container traffic.
- `host.docker.internal` is only used to reach an LLM running on the host
  (`extra_hosts: host-gateway` on the backend service).
- `.env` is the source of runtime configuration; compose `environment:` blocks
  only override values that *must* differ inside Docker.
