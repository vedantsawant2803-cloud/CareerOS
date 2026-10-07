# Security & Privacy

CareerOS is designed as a **public portfolio demo**: it must be safe to run
with the world watching — no exposed secrets, no leaking contact details, no
unauthenticated control planes.

## Threat model (summary)

| Risk | Mitigation |
| --- | --- |
| Committed secrets | `.gitignore` excludes `.env`, `.env.*` (templates `*.example` are the only committed env files); `gitleaks` runs in CI on every push/PR and weekly. |
| Unauthenticated API abuse | Optional `X-API-Key` guard on **all** `/api/v1` routes (`API_KEY_ENABLED=true`); production validation requires ≥ 16-char keys. Rate limiting is delegated to the reverse proxy. |
| Path traversal via ingestion | `IngestRequest.data_dir` accepts **relative paths only** — absolute paths, drive letters, and `..` segments are rejected with `422`. |
| Contact-info exposure | `SHOW_CONTACT_INFORMATION=false` by default; `/api/v1/profile` returns `contact: null`. Enabling it under `APP_ENV=production` **fails startup validation**. |
| Secret leakage via API | `/api/v1/config/status` exposes booleans only (`llm_api_key_configured`, `api_key_enabled`); secret values are never serialized into responses, logs, or health output. |
| CORS misconfiguration | `ALLOWED_ORIGINS` defaults to `*` for local dev; production **rejects** wildcard origins at startup. |
| Prompt-injection via corpus/JD | The system prompt instructs the model to answer only from retrieved context and to say when evidence is missing; input lengths are capped (`MAX_QUERY_LENGTH`, `MAX_JOB_DESCRIPTION_LENGTH`). |
| Unsafe LLM endpoint | `LLM_BASE_URL` must be `http(s)://…`; in production point it at a private network endpoint and inject `LLM_API_KEY` from a secret manager. |
| Vulnerable dependencies | `pip-audit` (weekly + per push) and `dependency-review` (fails on high-severity additions in PRs) workflows. |

## API authentication

```bash
# Enable (e.g. in .env):
API_KEY_ENABLED=true
API_KEY=<long-random-secret>        # ≥ 16 chars required in production

# Clients then send:
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/query -d '…'
```

- The guard lives in `backend/app/dependencies.py` (`require_api_key`) and is
  attached to the whole `/api/v1` router.
- `GET /health` is intentionally unguarded so Docker healthchecks and
  orchestrators can probe it without credentials.
- Wrong/missing key ⇒ `401` with the standard error envelope.

## Secrets management

- **Never** put real keys in `.env.example`, `.env.development.example`, or
  `.env.production.example` — they are committed templates with placeholders.
- Production: inject `LLM_API_KEY`, `API_KEY`, and vendor credentials through
  the hosting platform's secret manager (see the header of
  `.env.production.example`).
- `QDRANT_API_KEY` (for managed Qdrant) follows the same rule.
- CI needs no secrets to pass; tests run fully offline.

## Privacy: contact information

The corpus contains personal contact details (email, phone). Behavior:

| Setting | Effect |
| --- | --- |
| `SHOW_CONTACT_INFORMATION=false` (default) | `GET /api/v1/profile` returns `"contact": null`; the Streamlit UI does not render contact details. |
| `SHOW_CONTACT_INFORMATION=true` (dev only) | Contact fields are returned for local inspection. |
| `APP_ENV=production` + `true` | **Startup fails**: `SHOW_CONTACT_INFORMATION must be false in public/production mode`. |

`PUBLIC_PROFILE_MODE` (default `true`) controls the overall public-demo
posture; links (`GITHUB_URL`, `LINKEDIN_URL`, `PORTFOLIO_URL`) stay empty
unless explicitly configured.

## Transport & infrastructure

- Terminate **HTTPS** at a reverse proxy in front of backend and frontend.
- Keep Qdrant on a **private network**; never expose an unauthenticated
  Qdrant to the internet. The compose file publishes `6333` for local
  development only — remove or firewall it in production.
- Restrict exposed ports at the host firewall; only the proxy ports should be
  reachable externally.
- Run the backend as a non-root user in the container (see
  `backend/Dockerfile`).

## Reporting vulnerabilities

Please see [SECURITY.md](../SECURITY.md) for the private disclosure process.
Do not open public issues for security-sensitive reports.
