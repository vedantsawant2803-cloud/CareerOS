# CareerOS

**A citation-grounded RAG portfolio that answers questions about one real career — with sources.**

CareerOS ingests a small corpus of résumé, project, and event documents, indexes them
into Qdrant, and answers natural-language questions through a local, OpenAI-compatible
LLM. Every answer is grounded in retrieved chunks and returns explicit citations
(`source_file`, `section`, `quote`) so claims can be verified against the source
material. When no LLM is running, the API still returns retrieval results and
citations — it never fabricates an answer.

> **Privacy first:** contact information (email/phone) is hidden by default and only
> exposed when `SHOW_CONTACT_INFORMATION=true`. No secrets are ever committed, and
> `/api/v1/config/status` reports configuration as booleans only.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [Repository layout](#repository-layout)
- [Local LLM setup](#local-llm-setup)
- [Common commands](#common-commands)
- [API at a glance](#api-at-a-glance)
- [Documentation index](#documentation-index)
- [Consistency checklist](#consistency-checklist)
- [License](#license)

---

## Features

| Area | What it does |
| --- | --- |
| **Ingestion** | Loads Markdown/JSON/TXT documents, extracts title/section metadata, detects document types (project, case study, hackathon, profile…), chunks with overlap, and embeds into Qdrant. |
| **Retrieval** | Hybrid vector search + metadata filters (`project`, `document_type`, `technology`, `year`), optional cross-encoder reranking, keyword boost. |
| **Generation** | Six modes: `qa`, `project_summary`, `tailor_resume`, `interview_prep`, `skill_gap`, `resume_bullets`. `tailor_resume` and `skill_gap` require a `job_description`. |
| **Citations** | Every answer carries numbered citation cards with source file, section, and a verbatim quote; citation coverage is reported in metadata. |
| **Graceful degradation** | LLM unreachable ⇒ retrieval + citations are still returned with a clear warning instead of a fabricated answer. |
| **Frontend** | Streamlit UI: *Ask CareerOS*, *Explore Projects*, *Tailor for a Job*, *Interview Preparation*, *About the System*. |
| **Ops** | Docker Compose (`qdrant`, `backend`, `frontend`) with healthchecks, Makefile task runner, GitHub Actions CI/lint/security workflows. |
| **Quality** | 98 offline tests (no live LLM, Qdrant, or model downloads), ruff lint + format, 26-question evaluation harness. |

## Architecture

```
                       ┌───────────────────────────────────────────────┐
                       │                 Streamlit UI                 │
                       │  Ask · Projects · Tailor · Interview · About  │
                       └──────────────────────┬────────────────────────┘
                                              │ BACKEND_URL (http://backend:8000)
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ FastAPI backend — create_app(settings, container) composition root          │
│                                                                             │
│  /health                liveness probe (open)                              │
│  /api/v1/*              protected by optional X-API-Key                    │
│                                                                             │
│  routes ── CareerService ── Retriever ── QdrantStore                        │
│              │                  │            ▲                             │
│              │                  │            │ vectors                     │
│              ▼                  ▼            │                             │
│        AnswerGenerator    Reranker      Embedder (bge-small-en-v1.5)       │
│        (local OpenAI-     (optional)                                     │
│         compatible LLM)                                                  │
└───────────────┬────────────────────────────────────┬────────────────────────┘
                │                                    │
                ▼                                    ▼
        ┌───────────────┐                   ┌────────────────┐
        │ Ollama / local│                   │    Qdrant      │
        │ LLM endpoint  │                   │  collection:   │
        │ (llama3.1)    │                   │   career_os    │
        └───────────────┘                   └────────────────┘
```

**Query flow:** request validation → metadata/vector retrieval (top-K) → optional
rerank (top-N) → prompt assembly with numbered chunks → LLM generation → citation
extraction + coverage scoring → response with `citations`, `metadata`, and optional
`retrieved_chunks` debug view.

Design details live in [`docs/architecture.md`](docs/architecture.md).

## Quickstart

### Option A — Docker Compose (recommended)

```bash
git clone <your-fork-url> CareerOS
cd CareerOS
cp .env.example .env            # optional: compose also runs with built-in defaults
docker compose up --build       # qdrant + backend + frontend
```

Then, in a second terminal:

```bash
docker compose exec backend python scripts/seed_data.py   # index the corpus
```

| Service | URL |
| --- | --- |
| Streamlit UI | http://localhost:8501 |
| FastAPI (docs) | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Qdrant | http://localhost:6333/dashboard |

### Option B — local (bare metal)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

cp .env.development.example .env  # then edit URLs: QDRANT_URL=http://127.0.0.1:6333
python scripts/check_environment.py

# Terminal 1 — start Qdrant (Docker is the simplest way):
docker run -d --name careeros-qdrant -p 6333:6333 qdrant/qdrant:v1.12.4

# Terminal 2 — API:
python -m uvicorn app.main:app --app-dir backend --reload --port 8000

# Terminal 3 — UI:
streamlit run frontend/app.py
```

Index documents (either way):

```bash
python scripts/seed_data.py                          # local run
docker compose exec backend python scripts/seed_data.py   # in Docker
# or via API:
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"data_dir": "data/sample_docs", "reset": true}'
```

## Repository layout

```
CareerOS/
├── backend/
│   ├── app/
│   │   ├── api/               # routes, pydantic schemas, error handlers
│   │   ├── config.py          # typed settings (env-driven), fail-fast validation
│   │   ├── dependencies.py    # DI container, API-key guard
│   │   ├── generation/        # prompts, answer generator, citations
│   │   ├── ingestion/         # loaders, metadata, chunking, index pipeline
│   │   ├── main.py            # create_app() composition root
│   │   ├── retrieval/         # embedder, Qdrant store, filters, reranker, retriever
│   │   ├── services/          # career, ingestion, health services
│   │   └── utils/             # hashing, text, timing helpers
│   ├── Dockerfile
│   ├── requirements.txt       # runtime dependencies
│   └── requirements-dev.txt   # pytest, ruff, mypy, coverage
├── frontend/
│   ├── app.py                 # Streamlit UI (5 pages)
│   ├── .streamlit/config.toml
│   ├── Dockerfile
│   └── requirements.txt
├── data/
│   ├── sample_docs/           # 7 source documents (résumé, projects, events)
│   └── eval/questions.json    # 26 evaluation questions with expected points
├── scripts/
│   ├── seed_data.py           # index the corpus
│   ├── check_environment.py   # pre-flight dependency/version checks
│   ├── run_eval.py            # retrieval/answer evaluation harness
│   └── export_demo_data.py    # export a demo snapshot
├── tests/                     # unit · integration · api — fully offline
├── docs/                      # architecture, API, configuration, deployment, …
├── .github/                   # CI, lint, security workflows + community files
├── docker-compose.yml         # qdrant + backend + frontend (service-name networking)
├── docker-compose.dev.yml     # development overlay (reload-friendly)
├── Makefile                   # task runner (make help)
├── .env.example               # environment templates (dev/prod variants)
└── pyproject.toml             # project metadata, ruff, mypy configuration
```

## Local LLM setup

CareerOS talks to any **OpenAI-compatible** endpoint. Ollama is the default:

```bash
# 1. Install Ollama, then pull the model:
ollama pull llama3.1

# 2. Local run — point the backend at Ollama:
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=llama3.1

# 3. Docker run — reach the host from inside the container:
LLM_BASE_URL=http://host.docker.internal:11434/v1   # already the .env.example default
```

**No LLM? No problem.** The API answers with retrieved evidence and citation cards,
sets `metadata.used_llm=false`, and adds a warning explaining that a local LLM is
needed for natural-language answers. To use a hosted model instead, set
`LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_API_KEY` from your secret manager (never
from a committed file).

## Common commands

```bash
# Environment pre-flight
python scripts/check_environment.py

# Tests (offline: no live LLM, Qdrant, or model downloads)
python -m pytest tests -q          # or: make test

# Lint + format (same checks as CI)
python -m ruff check backend/app scripts tests     # or: make lint
python -m ruff format backend/app scripts tests    # or: make format

# Ingestion
python scripts/seed_data.py                          # index data/sample_docs
python scripts/seed_data.py --data-dir my_docs --reset   # custom corpus

# Evaluation (26 questions; retrieval metrics always, LLM-judge metrics only
# when JUDGE_BASE_URL/JUDGE_MODEL are configured — never fabricated)
python scripts/run_eval.py                           # or: make eval

# Docker stack
docker compose up --build -d     # make up
docker compose logs -f --tail=200    # make logs
docker compose down              # make down
make help                        # list all targets
```

## API at a glance

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service metadata (open) |
| `GET` | `/health` | Liveness/readiness (open, no auth) |
| `POST` | `/api/v1/query` | Ask a question (6 modes, filters, optional debug) |
| `POST` | `/api/v1/ingest` | Index documents (`data_dir`, `reset`) |
| `GET` | `/api/v1/profile` | Structured profile (contact gated by config) |
| `GET` | `/api/v1/projects` | Project exploration cards with citations |
| `GET` | `/api/v1/config/status` | Non-secret configuration snapshot |

All `/api/v1` routes accept an optional `X-API-Key` header when
`API_KEY_ENABLED=true`. Full request/response examples: [`docs/api.md`](docs/api.md).

## Documentation index

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, design decisions |
| [docs/api.md](docs/api.md) | Endpoints, payloads, error contract |
| [docs/configuration.md](docs/configuration.md) | Every environment variable, defaults, validation rules |
| [docs/deployment.md](docs/deployment.md) | Docker Compose, production checklist, CI |
| [docs/ingestion.md](docs/ingestion.md) | Pipeline stages, chunking rules, metadata extraction |
| [docs/evaluation.md](docs/evaluation.md) | Evaluation harness, metrics, adding questions |
| [docs/security.md](docs/security.md) | API key, secrets, privacy gating, scanning workflows |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common failures and fixes |
| [docs/resume-description.md](docs/resume-description.md) | Short project description for a résumé |

## Consistency checklist

Verified against the repository:

- [x] **Service names** — `qdrant` / `backend` / `frontend`; container-to-container
      traffic uses service names (`http://qdrant:6333`, `http://backend:8000`),
      never `localhost`; `host.docker.internal` is only for reaching the host LLM.
- [x] **Environment templates** — `.env.example`, `.env.development.example`, and
      `.env.production.example` match `Settings` fields in
      `backend/app/config.py` (names are case-insensitive env bindings).
- [x] **Endpoints** — README, `docs/api.md`, and `backend/app/api/routes.py` agree
      on all six routes; all `/api/v1` routes sit behind the optional API-key guard.
- [x] **Modes** — `qa`, `project_summary`, `tailor_resume`, `interview_prep`,
      `skill_gap`, `resume_bullets` are defined once in
      `backend/app/generation/prompts.py` and reused by API, UI, and docs.
- [x] **Secrets** — `.env*` files are ignored by git (templates are the only
      committed env files); `/api/v1/config/status` exposes booleans only;
      contact information is gated behind `SHOW_CONTACT_INFORMATION=false`.
- [x] **Tests offline** — `pytest tests` passes with no running LLM, Qdrant
      instance, or downloaded models (98 tests); CI runs the same command.
- [x] **No fabricated metrics** — the evaluation harness reports judge-based
      scores as `not_computed` when no judge endpoint is configured, and the
      corpus contains only verifiable facts.

## License

MIT — see [LICENSE](LICENSE).
