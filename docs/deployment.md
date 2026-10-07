# Deployment

## Local Docker Compose (recommended)

```bash
cp .env.example .env            # optional — works without it (built-in defaults)
docker compose up --build          # or: make up
docker compose exec backend python scripts/seed_data.py   # index corpus
```

Services:

| Service | Container | Port (host) | Internal URL |
| --- | --- | --- | --- |
| `qdrant` | `careeros-qdrant` | 6333 | `http://qdrant:6333` |
| `backend` | `careeros-backend` | 8000 | `http://backend:8000` |
| `frontend` | `careeros-frontend` | 8501 | — |

Networking rules:

- Containers reach each other by **Docker service name** — never `localhost`.
  `docker-compose.yml` enforces this: the backend always gets
  `QDRANT_URL=http://qdrant:6333`, and the frontend gets
  `BACKEND_URL=http://backend:8000`, regardless of `.env`.
- To reach an LLM running **on the host** (e.g. Ollama), the backend uses
  `LLM_BASE_URL=http://host.docker.internal:11434/v1` (the compose file adds
  `extra_hosts: host.docker.internal:host-gateway` so this works on Linux too).
- `./data` and `./scripts` are mounted into the backend container so
  documents can be (re)indexed without rebuilding the image.

Healthchecks & ordering: `qdrant` must be healthy before `backend` starts, and
`backend` must be healthy (responds on `/health`) before `frontend` starts.

### Development overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build   # or: make dev
```

The dev overlay layers reload-friendly settings on top of the base file.

### Everyday operations

```bash
make logs          # tail logs from all services
make seed          # re-run ingestion inside the backend container
make down          # stop the stack
make clean         # caches + compose volumes (drops Qdrant data)
```

## Bare-metal deployment

```bash
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python scripts/check_environment.py          # pre-flight checks

# Qdrant (if not already running):
docker run -d --name careeros-qdrant -p 6333:6333 qdrant/qdrant:v1.12.4

# API:
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

# UI:
streamlit run frontend/app.py
```

For a bare-metal run, point `.env` at `http://127.0.0.1:6333` (Qdrant) and
`http://127.0.0.1:11434/v1` (Ollama) — service names only resolve on the
Docker network.

## Production checklist

Before any public deployment (also enforced partly by settings validation):

1. **Secrets from the platform's secret manager** — never bake them into
   images, repos, or committed `.env` files: `LLM_API_KEY` (if hosted),
   `API_KEY`, any vendor credentials.
2. **`APP_ENV=production`** — enables fail-fast validation of the rules below.
3. **`ALLOWED_ORIGINS`** — explicit frontend origin(s); `*` is rejected.
4. **`API_KEY_ENABLED=true` + a strong `API_KEY`** (≥ 16 chars); clients send
   `X-API-Key: <value>`. Add rate limiting at the reverse proxy.
5. **`SHOW_CONTACT_INFORMATION=false`** — enabling it in production is
   rejected at startup.
6. **`ENABLE_DEBUG_ENDPOINTS=false`** — also rejected in production if true.
7. **Qdrant on a private network** — never a public unauthenticated URL; if it
   must be exposed, put it behind authenticated TLS.
8. **HTTPS termination** at a reverse proxy (nginx/Caddy/ALB) in front of
   backend and frontend; restrict ports at the host firewall.
9. **`LOG_LEVEL=INFO` or `WARNING`** — no debug logging in production.
10. **Health probes** — point orchestrator liveness/readiness checks at
    `GET /health` (no auth required).

A ready-made starting point: `.env.production.example`.

### Settings validation in production

These combinations fail at startup with a clear message instead of at runtime:

- wildcard `ALLOWED_ORIGINS`
- `ENABLE_DEBUG_ENDPOINTS=true`
- `SHOW_CONTACT_INFORMATION=true`
- `API_KEY_ENABLED=true` with a short/missing `API_KEY`

## LLM backends

| Backend | `LLM_BASE_URL` | Notes |
| --- | --- | --- |
| Ollama (local, default) | `http://127.0.0.1:11434/v1` (bare metal) / `http://host.docker.internal:11434/v1` (Docker) | `ollama pull llama3.1` first. No API key needed. |
| Local server (llama.cpp, vLLM, LM Studio, …) | any OpenAI-compatible `/v1` base URL | Set `LLM_MODEL` accordingly. |
| Hosted API | provider's OpenAI-compatible URL | Inject `LLM_API_KEY` from the secret manager. |

The backend degrades gracefully: if the LLM is down, `/api/v1/query` still
returns retrieval results and citations with `used_llm=false` and a warning.

## Continuous integration (GitHub Actions)

| Workflow | Trigger | What it runs |
| --- | --- | --- |
| `.github/workflows/ci.yml` | push/PR to `main` | `ruff check` + `ruff format --check`, `pytest tests` (offline, `APP_ENV=test`, `ENABLE_RERANKER=false`), `docker compose config -q` + image build. |
| `.github/workflows/lint.yml` | push to `main`, all PRs | Ruff lint/format; non-blocking `mypy`. |
| `.github/workflows/security.yml` | push/PR + weekly cron | `pip-audit` on backend requirements, `gitleaks` secret scan, `dependency-review` (fails on high-severity additions). |
| `.github/workflows/dependabot.yml` | scheduled | Weekly dependency update PRs (pip + GitHub Actions). |

No secrets are required for CI to pass; tests are fully mocked.

## Upgrading / re-indexing

```bash
git pull
docker compose up --build -d
docker compose exec backend python scripts/seed_data.py --reset   # rebuild collection
```

`--reset` (or `{"reset": true}` on `POST /api/v1/ingest`) drops and recreates
the collection — use it whenever `EMBEDDING_MODEL`/chunking settings change,
since vector dimensions and chunk ids depend on them.
