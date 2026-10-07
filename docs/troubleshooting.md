# Troubleshooting

## Pre-flight check

```bash
python scripts/check_environment.py
```

Reports Python version, required/optional packages, and `.env` presence with
clear OK/warn/error lines.

---

## Startup & configuration

### `CareerOS configuration is invalid: …`

Settings validation failed at startup. The message lists the exact problems,
e.g.:

| Message | Fix |
| --- | --- |
| `ALLOWED_ORIGINS must be restricted to explicit origins in production` | Set explicit origins, e.g. `ALLOWED_ORIGINS=https://your-frontend.example.com`. |
| `SHOW_CONTACT_INFORMATION must be false in public/production mode` | Set `SHOW_CONTACT_INFORMATION=false`. |
| `ENABLE_DEBUG_ENDPOINTS must be false in production` | Set `ENABLE_DEBUG_ENDPOINTS=false`. |
| `API_KEY must be at least 16 characters when API_KEY_ENABLED=true` | Use a longer random key. |
| `CHUNK_OVERLAP must be smaller than CHUNK_SIZE` | Lower `CHUNK_OVERLAP` or raise `CHUNK_SIZE`. |
| `TOP_N_RERANKED cannot exceed TOP_K_RETRIEVAL` | Raise `TOP_K_RETRIEVAL` or lower `TOP_N_RERANKED`. |
| `QDRANT_URL must start with http:// or https://` | Fix the URL (e.g. `http://qdrant:6333`). |

### `422` on `POST /api/v1/query`

- `"Unsupported mode '…'"` — use one of: `qa`, `project_summary`,
  `tailor_resume`, `interview_prep`, `skill_gap`, `resume_bullets`.
- `"mode='tailor_resume' requires a non-empty 'job_description'"` — include a
  `job_description` (also applies to `skill_gap`).
- `"query exceeds MAX_QUERY_LENGTH"` / `"job_description exceeds
  MAX_JOB_DESCRIPTION_LENGTH"` — shorten the input or raise the limit.

### `422` on `POST /api/v1/ingest`

`data_dir must be a relative path inside the workspace` — absolute paths,
drive letters, and `..` are rejected on purpose. Use `data/sample_docs` or
another workspace-relative directory.

### `401 Missing or invalid X-API-Key header`

`API_KEY_ENABLED=true` on the server. Send the header:

```bash
curl -H "X-API-Key: $API_KEY" …
```

---

## Qdrant

### `Could not check Qdrant collection` / connection refused

```bash
docker ps                     # is careeros-qdrant running?
docker compose logs qdrant
curl http://localhost:6333/    # dashboard reachable?
```

- Bare metal: make sure Qdrant is running
  (`docker run -d -p 6333:6333 qdrant/qdrant:v1.12.4`).
- Inside Docker the backend must use `QDRANT_URL=http://qdrant:6333`
  (service name, **not** `localhost`). `docker-compose.yml` forces this.
- Managed Qdrant: also set `QDRANT_API_KEY` and an `https://` URL.

### Queries return zero results

1. The corpus is probably not indexed yet:

   ```bash
   docker compose exec backend python scripts/seed_data.py
   # or: curl -X POST .../api/v1/ingest -d '{"data_dir": "data/sample_docs", "reset": true}'
   ```

2. A metadata filter may be too strict — `technology` must be an exact
   canonical name (`MySQL`, not `mysql db`).
3. After changing `EMBEDDING_MODEL` or chunking settings, re-index with
   `--reset` (vectors and chunk ids depend on them).

---

## LLM

### Answers say `used_llm: false` with a warning

The OpenAI-compatible endpoint is unreachable — the API still returns
retrieval results and citations (by design; it never fabricates). Fix:

```bash
# Ollama running?
ollama list
ollama pull llama3.1

# Bare metal (.env):        LLM_BASE_URL=http://127.0.0.1:11434/v1
# Docker       (.env):      LLM_BASE_URL=http://host.docker.internal:11434/v1
```

Then restart the backend. Verify with `GET /api/v1/config/status`
(`llm_base_url`, `llm_model`).

### LLM is slow or times out

- Increase `LLM_TIMEOUT_SECONDS` (default 120).
- Lower `LLM_MAX_TOKENS` or use a smaller model.
- Check GPU/CPU availability for the local server.

### Reranker warnings

`Reranker unavailable` / `Reranking disabled by configuration` — set
`ENABLE_RERANKER=true` and ensure `cross-encoder/ms-marco-MiniLM-L-6-v2` can
be downloaded, or accept vector-only ranking (a warning is attached, results
are still valid).

---

## Models (first run)

On first ingest/query the embedding model (`BAAI/bge-small-en-v1.5`, ~100 MB)
and optionally the reranker are downloaded by sentence-transformers. Behind a
proxy/offline, pre-download them or set `HF_HUB_OFFLINE=1` with a warm cache.

`pypdf` is optional — without it, `.pdf` ingestion is skipped with a warning;
Markdown/TXT/JSON still work.

---

## Frontend

### Streamlit can't reach the API

- Check `BACKEND_URL`: `http://backend:8000` under Docker,
  `http://localhost:8000` for bare metal.
- Confirm the backend health: `curl http://localhost:8000/health`.
- Docker ordering: the frontend starts only after the backend healthcheck
  passes — inspect `docker compose ps` and `docker compose logs backend`.

### CORS errors in the browser

`ALLOWED_ORIGINS` must include the Streamlit origin. Default `*` is fine for
local dev; in production list explicit origins (wildcards are rejected).

### Port already in use

Change ports in `.env` (`API_PORT`, `FRONTEND_PORT`) or stop the conflicting
process (`netstat -ano | findstr :8000`).

---

## Tests & CI

### Tests fail with import/URL errors

Run them offline-safe from the repo root — `tests/conftest.py` sets
`APP_ENV=test`, `ENABLE_RERANKER=false`, and points the LLM at a black-hole
URL so nothing external is contacted:

```bash
python -m pytest tests -q
```

Tests must never require a running LLM, Qdrant, or model downloads. If a test
tries to, that's a bug — please open an issue.

### `ruff` complaints locally but CI differs

Use the pinned range from `backend/requirements-dev.txt` and the same
commands as CI:

```bash
python -m ruff check backend/app scripts tests
python -m ruff format --check backend/app scripts tests
```

### Eval harness: `Backend not reachable …`

Start the stack and index first (`docker compose up --build`, then
`make seed`), or pass `--backend http://host:port` for a remote instance.

---

## Getting more detail

- Backend logs: `docker compose logs -f backend` (or uvicorn output).
- `GET /health` — dependency checks (`qdrant`, `llm`).
- `GET /api/v1/config/status` — effective non-secret configuration.
- `POST /api/v1/query` with `"include_debug": true` — inspect the exact
  chunks that were retrieved (ranks, scores, metadata).
