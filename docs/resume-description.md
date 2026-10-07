# Résumé Description

Short, factual project descriptions for a résumé or LinkedIn — pick the length
that fits. No invented metrics; every claim below is backed by the codebase.

---

## One-liner

**CareerOS** — a citation-grounded RAG platform (FastAPI · Qdrant · Streamlit ·
Docker) that answers career questions from a personal document corpus with
verifiable source citations and a local, privacy-first LLM.

---

## 3 bullets (recommended)

- Built **CareerOS**, an end-to-end RAG system (FastAPI, Qdrant, Streamlit) that
  answers questions from a personal corpus of résumé/project documents with
  **numbered citations** (source file, section, quote) and citation-coverage
  scoring — answers are traceable to their sources, and an offline fallback
  mode returns retrieved evidence instead of hallucinating when no LLM is
  available.
- Designed the **ingestion pipeline** (section-aware chunking with overlap and
  tiny-chunk merging, deterministic sha256 chunk ids, metadata extraction for
  document type/technologies/year) and **hybrid retrieval** (filtered vector
  search + keyword boost + optional cross-encoder reranking) behind swappable
  interfaces, with six query modes including résumé tailoring and skill-gap
  analysis against a job description.
- Ship-ready engineering: **98 offline tests** (no live services needed),
  ruff/mypy CI with Docker image builds, pip-audit + gitleaks security
  workflows, Docker Compose stack with healthchecks and service-name
  networking, a 26-question evaluation harness with honest `not_computed`
  LLM-judge metrics, and privacy-by-default config (contact info gated,
  secrets never exposed via API).

---

## 2 bullets (compact)

- Built **CareerOS**, a citation-grounded RAG portfolio (FastAPI · Qdrant ·
  Streamlit · Docker): section-aware chunking, hybrid retrieval with optional
  reranking, six query modes, and verifiable citations — with graceful
  offline fallback instead of fabricated answers.
- Ensured production-grade quality: 98 offline tests, GitHub Actions
  (lint/test/Docker build/security scanning), health-checked Compose stack,
  a 26-question eval harness with honest metrics, and privacy-by-default
  configuration.

---

## Paragraph (for a bio / project site blurb)

**CareerOS** is a retrieval-augmented generation system that answers questions
about one real career from a curated document corpus. Documents are loaded,
enriched with metadata (document type, technologies, years), chunked with
section-aware overlap, and embedded into Qdrant. Queries run through hybrid
retrieval — filtered vector search, keyword boosting, and optional
cross-encoder reranking — before a local OpenAI-compatible LLM drafts an
answer constrained to the retrieved context. Every answer returns numbered
citations (source file, section, verbatim quote) plus a citation-coverage
score, and when no LLM is reachable the API still returns the retrieved
evidence with an explicit warning rather than inventing content. The stack
ships with a Streamlit UI, Docker Compose orchestration with healthchecks,
an offline test suite, CI for lint/tests/container builds, dependency and
secret scanning, and a 26-question evaluation harness.

---

## Suggested bullets for different targets

**Backend / ML platform roles**

- Implemented a RAG pipeline with deterministic chunk ids, metadata filters
  pushed down to the vector store, and a rerank stage behind an abstraction
  that degrades gracefully when the model is unavailable.
- Added an evaluation harness (source recall, citation coverage, point
  coverage) with an opt-in LLM judge — metrics are reported as
  `not_computed` rather than fabricated when no judge is configured.

**Full-stack / product roles**

- Built a five-page Streamlit interface (ask, explore projects, tailor for a
  job, interview prep, system status) over a versioned REST API with a strict
  request/validation contract and uniform error envelopes.
- Enforced privacy-by-default: contact information hidden unless explicitly
  enabled (and rejected in production config), secrets exposed as booleans
  only, optional API-key auth on every v1 route.

---

## Notes for editing

- Keep only claims you can demonstrate — the repository is the evidence.
- If you add real metrics (stars, users, latency numbers), make sure they are
  measured and reproducible; this project deliberately ships **no invented
  numbers**.
- The interview-prep and skill-gap modes make good talking points: they show
  how job-description input is validated (required fields, length caps) and
  grounded against the same corpus.
