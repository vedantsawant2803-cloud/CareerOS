# Evaluation

CareerOS ships a deterministic evaluation harness that measures whether answers
are **grounded in the right sources** — not whether they sound plausible.

## Dataset

`data/eval/questions.json` — 26 questions:

```json
{
  "id": "q001",
  "question": "Which projects demonstrate backend engineering?",
  "category": "skills",
  "expected_points": ["Node.js", "Express", "REST APIs"],
  "expected_sources": ["devlens.md", "enviromonitor.md"]
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable identifier (used in the report). |
| `question` | Question sent to `POST /api/v1/query` (mode `qa` unless specified). |
| `category` | Grouping label (e.g. `skills`, `projects`). |
| `expected_points` | Facts a correct, grounded answer must contain (checked case-insensitively against the answer text). |
| `expected_sources` | Source files the answer's citations should reference. |
| `mode` / `job_description` | Optional — some questions exercise non-`qa` modes. |

## Running

```bash
# Stack must be running and the corpus indexed first:
docker compose up --build -d
docker compose exec backend python scripts/seed_data.py

python scripts/run_eval.py                          # or: make eval
python scripts/run_eval.py --backend http://localhost:8000 --limit 5
python scripts/run_eval.py --fail-under 0.6         # CI-style threshold gate
```

Flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--backend` | `EVAL_BACKEND_URL` or `http://localhost:8000` | Backend base URL. |
| `--dataset` | `data/eval/questions.json` | Question set path. |
| `--output` | `exports/eval_report.json` | Report destination (JSON). |
| `--limit N` | `0` (all) | Evaluate only the first N questions. |
| `--fail-under X` | unset | Exit non-zero when mean `point_coverage < X`. |
| `--timeout` | `EVAL_TIMEOUT_SECONDS` or `120` | Per-request timeout (seconds). |

The harness checks `/health` first and exits with a clear
"start the stack" message if the backend is unreachable.

## Metrics

Computed for every question (error-free responses only):

| Metric | Definition |
| --- | --- |
| `retrieval_hit_rate` | Share of questions where ≥ 1 chunk was retrieved. |
| `expected_source_hit_rate` | Share of questions whose citations include ≥ 1 expected source. |
| `expected_source_recall` | Mean share of expected sources cited. |
| `citation_coverage` | Mean share of retrieved chunks referenced by `[n]` markers (from API metadata). |
| `point_coverage` | Mean share of `expected_points` present in the answer text. |
| `answer_citation_marker_rate` | Share of answers containing `[n]` markers. |
| `response_length_words_mean` / `response_length_chars_mean` | Answer length. |
| `latency_ms_mean` | Mean end-to-end latency. |

### LLM-judge metrics — computed only when configured

`faithfulness` and `relevance` are produced by an external judge **only** when
both `JUDGE_BASE_URL` and `JUDGE_MODEL` are set (and the `openai` package is
installed). Otherwise they are reported explicitly as:

```json
"faithfulness": "not_computed (LLM judge unavailable: JUDGE_BASE_URL/JUDGE_MODEL unset)"
```

The report sets `metric_mode` to `"deterministic heuristics"` in that case.
**No score is ever fabricated.** This keeps results reproducible on machines
without any LLM.

## Report

Written to `exports/eval_report.json` (git-ignored):

```json
{
  "generated_at": "2026-10-07T12:00:00+00:00",
  "backend": "http://localhost:8000",
  "dataset": ".../data/eval/questions.json",
  "metric_mode": "deterministic heuristics",
  "metric_definitions": { "…": "…" },
  "metrics": { "point_coverage": 0.91, "…": 0 },
  "results": [
    {
      "id": "q001",
      "answer": "…",
      "expected_source_recall": 1.0,
      "point_coverage": 1.0,
      "missing_points": [],
      "confidence": "medium",
      "used_llm": true,
      "warnings": []
    }
  ]
}
```

Per-question results include `missing_points`, `error` (if any), retrieval
counts, and warnings, so regressions are easy to localize.

## Adding questions

1. Append an entry to `data/eval/questions.json` with `id`, `question`,
   `category`, `expected_points`, and `expected_sources`.
2. Only record facts that actually exist in `data/sample_docs/` — the corpus
   is the single source of truth.
3. Re-run `python scripts/run_eval.py --limit 1`-style spot checks, then the
   full set.

Keep `expected_points` short and literal (technology names, project names,
concrete facts) — matching is textual and case-insensitive.
