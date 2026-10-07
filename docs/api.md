# API Reference

Base URL (local): `http://localhost:8000`

- Interactive docs: `http://localhost:8000/docs` (Swagger UI), `/redoc` for ReDoc.
- API prefix: `API_PREFIX` (default `/api/v1`).
- Version: returned by `GET /health` and `GET /api/v1/config/status`.

## Authentication

All `/api/v1/*` routes accept an **optional** `X-API-Key` header:

- When `API_KEY_ENABLED=false` (default in dev), the header is ignored.
- When `API_KEY_ENABLED=true`, requests without the correct key get `401`.
- `GET /health` is never guarded so load balancers and Docker healthchecks
  can probe it without credentials.

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/profile
```

## Errors

Errors use a uniform envelope:

```json
{ "detail": "human-readable message", "type": "validation_error" }
```

| Status | Meaning |
| --- | --- |
| `400` | Business-rule violation (e.g. ingestion precondition). |
| `401` | Missing/incorrect `X-API-Key` when API-key auth is enabled. |
| `404` | Unknown route. |
| `422` | Request validation failure (schema, mode, length limits). |
| `500` | Unexpected server error (logged with a request id). |

---

## GET /

Service metadata (open, no API key).

```bash
curl http://localhost:8000/
```

```json
{
  "service": "CareerOS",
  "version": "1.0.0",
  "tagline": "A citation-grounded AI assistant for exploring Vedant Sawant's projects, technical skills, hackathon experience, and software engineering profile.",
  "api_prefix": "/api/v1",
  "docs": "/docs",
  "health": "/health"
}
```

---

## GET /health

Liveness/readiness probe. Open (no API key).

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "1.0.0",
  "environment": "development",
  "ready": true,
  "checks": {
    "qdrant": { "reachable": true, "collection_points": 42 },
    "embeddings": { "model": "BAAI/bge-small-en-v1.5", "library_available": true },
    "reranker": {
      "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
      "enabled": true,
      "available": true
    },
    "llm": {
      "provider": "ollama",
      "model": "llama3.1",
      "base_url": "http://127.0.0.1:11434/v1",
      "client_available": true
    }
  }
}
```

`status` is `ok` / `degraded` / `unavailable`, and `ready` reflects whether
core dependencies (Qdrant + embedding library) are usable — useful for Docker
healthchecks. `checks` never contains secrets.

---

## POST /api/v1/query

The core endpoint. Answer a career question with citations.

### Request body

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | yes | Non-empty; max `MAX_QUERY_LENGTH` (default 2000). |
| `mode` | string | no | `qa` (default), `project_summary`, `tailor_resume`, `interview_prep`, `skill_gap`, `resume_bullets`. |
| `job_description` | string | conditional | **Required** for `tailor_resume` and `skill_gap`; max `MAX_JOB_DESCRIPTION_LENGTH` (default 12000). |
| `filters` | object | no | `project`, `document_type`, `technology`, `year` (1900–2100). Blank strings are treated as `null`. |
| `include_debug` | boolean | no | When `true`, the response includes `retrieved_chunks`. |

### Example — general question

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
        "query": "Which projects demonstrate backend engineering?",
        "mode": "qa",
        "filters": { "technology": "Node.js" },
        "include_debug": false
      }'
```

### Example — tailoring a résumé (job description required)

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
        "query": "Tailor my experience for this role",
        "mode": "tailor_resume",
        "job_description": "Backend engineer building REST APIs with Node.js and SQL databases..."
      }'
```

Omitting `job_description` for `tailor_resume`/`skill_gap` returns a `422`
error explaining the requirement.

### Response

```json
{
  "answer": "DevLens demonstrates backend engineering with Node.js and Express REST APIs [1]. ...",
  "mode": "qa",
  "citations": [
    {
      "source_file": "devlens.md",
      "document_type": "project",
      "title": "DevLens",
      "section": "Overview",
      "chunk_id": "…sha256-based id…",
      "quote": "DevLens is a code review tool ..."
    }
  ],
  "retrieved_chunks": [],
  "metadata": {
    "retrieval_count": 5,
    "latency_ms": 412.7,
    "llm_model": "llama3.1",
    "confidence": "medium",
    "used_llm": true,
    "citation_coverage": 0.8,
    "warnings": []
  }
}
```

Notes:

- `retrieved_chunks` is populated only when `include_debug=true` (rank, scores,
  text, and metadata per chunk).
- When no LLM is reachable, `used_llm` is `false`, `answer` still contains the
  retrieved evidence with `[n]` markers, and `warnings` explains that a local
  LLM is needed for natural-language answers.
- `confidence` is derived from retrieval signal, never invented.

### Mode summary

| Mode | Job description | Typical use |
| --- | --- | --- |
| `qa` | — | Free-form questions about the profile. |
| `project_summary` | — | Structured summary of a project (optionally pinned with `filters.project`). |
| `tailor_resume` | **required** | Map experience onto a specific job posting. |
| `skill_gap` | **required** | Compare skills against a posting's requirements. |
| `interview_prep` | — | Likely interview questions grounded in real projects. |
| `resume_bullets` | — | Résumé bullet points derived from the corpus. |

---

## POST /api/v1/ingest

Index documents into Qdrant.

### Request body

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `data_dir` | string | `"data/sample_docs"` | Must be a **relative** path inside the workspace. Absolute paths, drive letters, and `..` are rejected with `422`. |
| `reset` | boolean | `false` | Drop and rebuild the collection first. |

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"data_dir": "data/sample_docs", "reset": true}'
```

### Response

```json
{
  "documents": 7,
  "chunks": 42,
  "indexed": 42,
  "skipped": 0,
  "collection": "career_os",
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "data_dir": "data/sample_docs",
  "reset": true,
  "warnings": []
}
```

Documents larger than `MAX_DOCUMENT_LENGTH` are skipped and reported in
`warnings`; they still count toward `skipped`.

---

## GET /api/v1/profile

Structured public profile parsed from the corpus.

```bash
curl http://localhost:8000/api/v1/profile
```

```json
{
  "name": "Vedant Sawant",
  "title": "…",
  "location": "…",
  "summary": "…",
  "education": [ { "…": "…" } ],
  "skills": { "Languages": ["…"], "…": ["…"] },
  "engineering_strengths": ["…"],
  "current_learning": ["…"],
  "contact": null,
  "links": { "github": "", "linkedin": "", "portfolio": "" },
  "public_profile_mode": true,
  "sources": [ { "source_file": "vedant_resume.md", "section": "…" } ]
}
```

**Contact gating:** `contact` is `null` unless `SHOW_CONTACT_INFORMATION=true`.
This is enforced in code and validated at startup in production (where
enabling it raises a configuration error).

---

## GET /api/v1/projects

Project exploration cards, each with a citation back to its source document.

```bash
curl http://localhost:8000/api/v1/projects
```

```json
[
  {
    "name": "DevLens",
    "subtitle": "…",
    "document_type": "project",
    "source_file": "devlens.md",
    "technologies": ["Node.js", "Express"],
    "description": "…",
    "engineering_themes": ["…"],
    "citation": {
      "source_file": "devlens.md",
      "document_type": "project",
      "title": "DevLens",
      "section": "Overview",
      "quote": "…"
    }
  }
]
```

---

## GET /api/v1/config/status

Non-secret configuration snapshot. **Secrets are never included** — API keys
and tokens appear only as booleans (`api_key_enabled`,
`llm_api_key_configured`).

```bash
curl http://localhost:8000/api/v1/config/status
```

```json
{
  "version": "1.0.0",
  "app_env": "development",
  "api_prefix": "/api/v1",
  "qdrant_url": "http://qdrant:6333",
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "reranker_enabled": true,
  "llm_provider": "ollama",
  "llm_model": "llama3.1",
  "llm_api_key_configured": false,
  "api_key_enabled": false,
  "show_contact_information": false,
  "links": { "github": "", "linkedin": "", "portfolio": "" }
}
```

The full field list is defined by `ConfigStatus` in
`backend/app/api/schemas.py`.
