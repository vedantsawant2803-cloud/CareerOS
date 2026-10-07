# Configuration

CareerOS is configured entirely through environment variables (pydantic-settings,
case-insensitive). Local `.env` files are read automatically; the committed
templates are:

| File | Audience |
| --- | --- |
| `.env.example` | Safe defaults for local Docker development (copy to `.env`). |
| `.env.development.example` | Development overlay: debug logging, debug endpoints on. |
| `.env.production.example` | Production guidance: CORS restrictions, API key, secret-injection notes. |

```bash
cp .env.example .env
```

Never commit a real `.env` file or real API keys — `.gitignore` excludes
`.env*` except the committed `*.example` templates.

---

## Application

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `development` | One of `development`, `test`, `production`, `staging`. |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, …). |

## HTTP server

| Variable | Default | Description |
| --- | --- | --- |
| `API_HOST` | `0.0.0.0` | Bind address. |
| `API_PORT` | `8000` | Port (1–65535). |
| `API_PREFIX` | `/api/v1` | Must start with `/`; trailing slashes are stripped. |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins. **Must be explicit origins in production.** |
| `API_KEY_ENABLED` | `false` | Require `X-API-Key` on all `/api/v1` routes. |
| `API_KEY` | `` | The expected key. Must be ≥ 16 characters when enabled in production. |

## Frontend

| Variable | Default | Description |
| --- | --- | --- |
| `FRONTEND_PORT` | `8501` | Streamlit port. |
| `BACKEND_URL` | `http://localhost:8000` | Backend base URL as seen by the UI. **Use `http://backend:8000` under Docker** (compose sets this automatically). |
| `API_PREFIX` | `/api/v1` | Read by the frontend to build request URLs; must match the backend. |
| `API_KEY` | `` | Sent as `X-API-Key` by the UI when the backend has auth enabled. |
| `FRONTEND_TIMEOUT_SECONDS` | `90` | Per-request HTTP timeout in the Streamlit UI. |

## Vector store (Qdrant)

| Variable | Default | Description |
| --- | --- | --- |
| `QDRANT_URL` | `http://localhost:6333` | Must start with `http://` or `https://`. **Use `http://qdrant:6333` under Docker** (compose forces this for the backend). |
| `QDRANT_COLLECTION` | `career_os` | Collection name. |
| `QDRANT_API_KEY` | `` | Optional API key for managed Qdrant (cloud). |

## Embedding & reranking

| Variable | Default | Description |
| --- | --- | --- |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Sentence-transformers model (downloaded on first run). |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder for reranking. |
| `ENABLE_RERANKER` | `true` | Set `false` to skip the reranker (tests and CI do this). |
| `KEYWORD_BOOST` | `0.15` | Keyword-overlap boost added to vector scores (0.0–1.0). |

## LLM (OpenAI-compatible endpoint)

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | Label for logs/status (e.g. `ollama`, `openai_compatible`). |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | Any OpenAI-compatible base URL. **Use `http://host.docker.internal:11434/v1` under Docker** (the `.env.example` default) to reach Ollama on the host. |
| `LLM_MODEL` | `llama3.1` | Model name passed to the endpoint. |
| `LLM_API_KEY` | `` | Optional; local servers ignore it (the SDK still receives a placeholder). Inject from a secret manager for hosted LLMs. |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature (0.0–2.0). Low = more faithful. |
| `LLM_MAX_TOKENS` | `1200` | Max completion tokens (64–8192). |
| `LLM_TIMEOUT_SECONDS` | `120` | Request timeout (1–600). |

If the endpoint is unreachable, queries still succeed with retrieved evidence
and citations plus `used_llm=false` and an explanatory warning.

## Retrieval & chunking

| Variable | Default | Description |
| --- | --- | --- |
| `TOP_K_RETRIEVAL` | `20` | Candidate count from vector search (1–200). |
| `TOP_N_RERANKED` | `5` | Final chunks kept after rerank (1–50). **Must be ≤ `TOP_K_RETRIEVAL`.** |
| `CHUNK_SIZE` | `1200` | Target characters per chunk (200–8000). |
| `CHUNK_OVERLAP` | `150` | Overlap between chunks (0–2000). **Must be < `CHUNK_SIZE`.** |
| `MIN_CHUNK_LENGTH` | `80` | Chunks shorter than this are merged into a neighbour (0–2000). |

## Input limits

| Variable | Default | Description |
| --- | --- | --- |
| `MAX_QUERY_LENGTH` | `2000` | Max characters in `query` (50–50 000). |
| `MAX_JOB_DESCRIPTION_LENGTH` | `12000` | Max characters in `job_description` (100–200 000). |
| `MAX_DOCUMENT_LENGTH` | `100000` | Documents above this size are skipped at ingestion (1 000–5 000 000). |

## Privacy & public demo

| Variable | Default | Description |
| --- | --- | --- |
| `PUBLIC_PROFILE_MODE` | `true` | Public-demo posture for profile exposure. |
| `SHOW_CONTACT_INFORMATION` | `false` | When `false`, `contact` is `null` in `/api/v1/profile`. **Must remain `false` in production.** |
| `ENABLE_DEBUG_ENDPOINTS` | `false` | Extra debug routes. **Must remain `false` in production.** |

## Public links

| Variable | Default | Description |
| --- | --- | --- |
| `GITHUB_URL` | `` | Shown by the UI/config status when set. |
| `LINKEDIN_URL` | `` | Same. |
| `PORTFOLIO_URL` | `` | Same. |

## Paths

| Variable | Default | Description |
| --- | --- | --- |
| `DATA_DIR` | `data/sample_docs` | Default corpus directory for ingestion. |
| `EVAL_FILE` | `data/eval/questions.json` | Evaluation question set. |

## Evaluation-only variables (scripts/run_eval.py)

Read directly from the environment by the eval harness (and other scripts),
never by the API:

| Variable | Default | Description |
| --- | --- | --- |
| `EVAL_BACKEND_URL` | `http://localhost:8000` | Default backend for `scripts/run_eval.py` (overridable with `--backend`). |
| `EVAL_TIMEOUT_SECONDS` | `120` | Per-request timeout for evaluation runs. |
| `JUDGE_BASE_URL` | `` | OpenAI-compatible endpoint used as an LLM judge. |
| `JUDGE_MODEL` | `` | Judge model name. |
| `JUDGE_API_KEY` | `` | Optional key for the judge endpoint (local servers ignore it). |

When `JUDGE_BASE_URL`/`JUDGE_MODEL` are unset, judge-based metrics are
reported as `not_computed` — scores are **never fabricated**.

`scripts/check_environment.py` and `scripts/export_demo_data.py` also read
`BACKEND_URL`, `QDRANT_URL`, `LLM_BASE_URL`, `API_PREFIX`, `API_KEY`, and
`API_KEY_ENABLED` from the same environment as the backend.

---

## Validation rules

Settings are validated at startup (`Settings.validate_environment()`); invalid
combinations fail fast with an actionable message instead of surfacing later:

- `API_PREFIX` must start with `/`.
- `APP_ENV` must be one of `development`, `test`, `production`, `staging`.
- `QDRANT_URL`, `LLM_BASE_URL`, `BACKEND_URL` must be `http(s)://…`
  (trailing slashes are stripped).
- `CHUNK_OVERLAP < CHUNK_SIZE`.
- `TOP_N_RERANKED <= TOP_K_RETRIEVAL`.

**Production (`APP_ENV=production`) additionally requires:**

- `ALLOWED_ORIGINS` restricted to explicit origins (no `*`).
- `ENABLE_DEBUG_ENDPOINTS=false`.
- `SHOW_CONTACT_INFORMATION=false`.
- If `API_KEY_ENABLED=true`, `API_KEY` must be at least 16 characters.

Example of a startup failure:

```
CareerOS configuration is invalid:
- ALLOWED_ORIGINS must be restricted to explicit origins in production
- SHOW_CONTACT_INFORMATION must be false in public/production mode
```
