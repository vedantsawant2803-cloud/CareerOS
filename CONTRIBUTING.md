# Contributing to CareerOS

Thanks for your interest in improving CareerOS. This project has one hard rule:
**every factual claim about the candidate must be traceable to a source document
in `data/sample_docs/`.**

## Ground rules

1. **No fabricated facts.** Do not add metrics, awards, employers, technologies,
   team sizes, or outcomes that are not present in the verified source documents.
2. **No secrets.** Never commit `.env` files, API keys, or personal contact
   information (phone number, personal email) in public UI code or docs.
3. **Citations stay on.** Any change to generation must preserve per-answer
   citations and the "not enough information" fallback.

## Getting started

```bash
git clone <repository-url>
cd career-os
cp .env.example .env
docker compose up --build
docker compose exec backend python scripts/seed_data.py
```

## Development workflow

1. Fork and create a feature branch from `main`.
2. Make your change with tests.
3. Run the quality gates:

```bash
make lint
make test
make eval
```

4. Open a pull request using the template.

## Adding or editing source documents

- Put Markdown documents in `data/sample_docs/`.
- Keep a top-level `# Title` heading — it becomes the citation title.
- Use `##` / `###` headings for sections — citations reference them.
- Re-run `python scripts/seed_data.py --reset` after editing documents so the
  index matches the files.

## Code style

- Python 3.11+, formatted and linted with Ruff (`make format`).
- Keep module boundaries: `ingestion`, `retrieval`, `generation`, `services`,
  `api`, `utils`.
- Configuration comes from `app/config.py` (pydantic-settings), never from
  hard-coded constants.

## Commit messages

Use concise, imperative messages: `fix: guard reranker load failure`,
`docs: document evaluation metrics`.

## Reporting issues

Use the GitHub issue templates. Redact secrets and personal data from logs.
