# Changelog

All notable changes to CareerOS are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-07

### Added

- FastAPI backend with `/health`, `/api/v1/ingest`, `/api/v1/query`,
  `/api/v1/profile`, `/api/v1/projects`, and `/api/v1/config/status`.
- Six query modes: `qa`, `project_summary`, `tailor_resume`, `interview_prep`,
  `skill_gap`, `resume_bullets`.
- Structure-aware Markdown ingestion pipeline with deterministic document and
  chunk IDs, content hashing, and safe re-indexing.
- Dense vector retrieval over Qdrant with metadata filtering, optional keyword
  boosting, cross-encoder reranking, and confidence estimation.
- Citation-grounded generation with per-mode prompts and a strict
  "not enough information" fallback.
- Streamlit frontend with Ask CareerOS, Explore Projects, Tailor for a Job,
  Interview Preparation, and About pages.
- Verified sample corpus: resume, DevLens, EnviroMonitor, Apartment Visitor
  Security System, GDG and SIES hackathons, LinkedIn summary.
- Evaluation harness (`scripts/run_eval.py`) with retrieval hit rate,
  expected-source hit rate, citation coverage, point coverage, and response
  length metrics over 20+ questions.
- Docker Compose stack (qdrant, backend, frontend) plus a development override
  with hot reload.
- Unit, integration, and API tests that run without live LLM or Qdrant
  services.
- Documentation: architecture, API, configuration, deployment, evaluation,
  ingestion, security, troubleshooting, resume description.

[1.0.0]: https://github.com/vedant-sawant/careeros/releases/tag/v1.0.0
