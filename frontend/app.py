"""CareerOS — Streamlit frontend.

A citation-grounded assistant UI with five pages:

1. Ask CareerOS            — chat-style Q&A with citations + retrieved context
2. Explore Projects        — cards for projects and hackathons
3. Tailor for a Job        — job-description tailoring / skill gap / bullets
4. Interview Preparation   — grounded interview Q&A material
5. About the System        — how the RAG pipeline works + privacy notes

All data comes from the CareerOS backend API (``BACKEND_URL``).
Contact details are never rendered unless the backend explicitly enables them.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration (Docker service names in compose, localhost for bare-metal runs)
# ---------------------------------------------------------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_PREFIX = os.getenv("API_PREFIX", "/api/v1")
API_KEY = os.getenv("API_KEY", "")
REQUEST_TIMEOUT = float(os.getenv("FRONTEND_TIMEOUT_SECONDS", "90"))

PAGE_ASK = "Ask CareerOS"
PAGE_PROJECTS = "Explore Projects"
PAGE_TAILOR = "Tailor for a Job"
PAGE_INTERVIEW = "Interview Preparation"
PAGES = [PAGE_ASK, PAGE_PROJECTS, PAGE_TAILOR, PAGE_INTERVIEW, "About the System"]

MODE_LABELS: dict[str, str] = {
    "qa": "General Q&A",
    "project_summary": "Project Summary",
    "tailor_resume": "Tailor Resume",
    "interview_prep": "Interview Prep",
    "skill_gap": "Skill-Gap Analysis",
    "resume_bullets": "Resume Bullets",
}

EXAMPLE_QUESTIONS = [
    "What technologies has Vedant worked with?",
    "Which projects demonstrate backend engineering?",
    "Which projects involve AI?",
    "What is DevLens?",
    "What engineering practices were used in EnviroMonitor?",
    "What security-focused work has Vedant done?",
    "What databases has Vedant used?",
    "What leadership experience does Vedant have?",
    "What happened at the GDG Hackathon?",
    "What recognition did Vedant receive at the SIES Hackathon?",
    "Which project best demonstrates developer tooling?",
    "Which projects are relevant to a backend internship?",
    "Summarize Vedant's profile for a software engineering role.",
    "Generate interview questions about DevLens.",
    "Which requirements are not currently verified?",
    "Generate accurate resume bullets for an AI engineering internship.",
]

MODE_HELP = {
    "qa": "Answer a question about the profile using indexed sources only.",
    "project_summary": "Summarize one or more indexed projects.",
    "tailor_resume": "Match the profile to a job description (requires JD).",
    "interview_prep": "Generate grounded interview questions and answer outlines.",
    "skill_gap": "Compare a job description against verified skills (requires JD).",
    "resume_bullets": "Write accurate resume bullets from verified sources.",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the backend; raises ``httpx.HTTPError`` on failure."""
    url = f"{BACKEND_URL}{API_PREFIX}{path}"
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=api_headers()) as client:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            raise BackendError(_error_message(response))
        return response.json()


def api_get(path: str) -> Any:
    url = f"{BACKEND_URL}{API_PREFIX}{path}"
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=api_headers()) as client:
        response = client.get(url)
        if response.status_code >= 400:
            raise BackendError(_error_message(response))
        return response.json()


class BackendError(RuntimeError):
    """User-presentable backend failure."""


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    except Exception:  # noqa: BLE001 - fall back to raw text
        pass
    text = (response.text or "").strip()
    return text[:300] or f"Backend returned HTTP {response.status_code}"


def fetch_health() -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=5, headers=api_headers()) as client:
            response = client.get(f"{BACKEND_URL}/health")
            if response.status_code == 200:
                return response.json()
    except Exception:  # noqa: BLE001 - health is best-effort
        return None
    return None


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def render_citations(citations: list[dict[str, Any]]) -> None:
    if not citations:
        st.info("No citations were attached to this answer.")
        return
    st.subheader("Citations")
    for index, citation in enumerate(citations, start=1):
        doc_type = str(citation.get("document_type", "document")).title()
        with st.container(border=True):
            left, right = st.columns([4, 1])
            left.markdown(
                f"**[{index}] {citation.get('title', '')}** — {citation.get('section', '')}  \n"
                f"`{citation.get('source_file', '')}` · {doc_type}"
            )
            right.caption(f"id `{str(citation.get('chunk_id', ''))[:10]}…`")
            quote = citation.get("quote", "")
            if quote:
                st.markdown(f"> {quote}")


def render_retrieved_chunks(chunks: list[dict[str, Any]]) -> None:
    with st.expander("Inspect retrieved context", expanded=False):
        if not chunks:
            st.caption("No chunks were retrieved for this query.")
            return
        for chunk in chunks:
            scores = f"vector={chunk.get('vector_score')}"
            if chunk.get("rerank_score") is not None:
                scores += f" · rerank={chunk.get('rerank_score')}"
            st.markdown(
                f"**#{chunk.get('rank')} — {chunk.get('title')} / {chunk.get('section')}**"
            )
            st.caption(
                f"`{chunk.get('source_file')}` · {chunk.get('document_type')} · {scores}"
            )
            st.text(chunk.get("text", "")[:1200])
            st.divider()


def render_metadata(metadata: dict[str, Any]) -> None:
    warnings = metadata.get("warnings") or []
    confidence = str(metadata.get("confidence", "unknown"))
    confidence_icon = {"high": "🟢", "medium": "🟡", "low": "🟠", "none": "🔴"}.get(
        confidence, "⚪"
    )
    st.caption(
        f"{confidence_icon} confidence: **{confidence}** · "
        f"sources: **{metadata.get('retrieval_count', 0)}** · "
        f"latency: **{metadata.get('latency_ms', 0)} ms** · "
        f"model: `{metadata.get('llm_model', 'n/a')}`"
    )
    if warnings:
        with st.expander(f"ℹ️ {len(warnings)} system note(s)", expanded=False):
            for warning in warnings:
                st.caption(f"• {warning}")


def run_query(
    query: str,
    mode: str,
    job_description: str | None = None,
    filters: dict[str, Any] | None = None,
    include_debug: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "job_description": job_description,
        "filters": filters or {},  # type: ignore[dict-item]
        "include_debug": include_debug,
    }
    return api_post("/query", payload)


def render_query_result(result: dict[str, Any]) -> None:
    st.subheader("Answer")
    st.markdown(result.get("answer", ""))
    render_citations(result.get("citations", []))
    render_retrieved_chunks(result.get("retrieved_chunks", []))
    render_metadata(result.get("metadata", {}))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_ask_career_os() -> None:
    st.header("💬 Ask CareerOS")
    st.caption(
        "Answers are generated only from indexed source documents and always include citations."
    )

    left, right = st.columns([2, 1])
    with right:
        mode = st.selectbox(
            "Mode",
            options=list(MODE_LABELS.keys()),
            format_func=lambda key: MODE_LABELS[key],
            help="Select how CareerOS should answer.",
        )
        st.caption(MODE_HELP.get(mode, ""))

    with left:
        st.markdown("##### Example questions")
        cols = st.columns(2)
        for index, example in enumerate(EXAMPLE_QUESTIONS[:12]):
            if cols[index % 2].button(
                example, key=f"example_{index}", use_container_width=True
            ):
                st.session_state["ask_query"] = example

    job_description = None
    if mode in {"tailor_resume", "skill_gap"}:
        job_description = st.text_area(
            "Job description (required for this mode)",
            key="ask_jd",
            height=220,
            placeholder="Paste the full job description here…",
        )

    query = st.text_area(
        "Your question",
        key="ask_query",
        height=120,
        placeholder="e.g. Which projects demonstrate backend engineering?",
    )

    filters = {"project": None, "document_type": None, "technology": None, "year": None}
    with st.expander("Optional filters", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        filters["project"] = col1.text_input("Project", placeholder="DevLens")
        filters["document_type"] = col2.selectbox(
            "Document type", ["", "project", "hackathon", "resume", "profile"]
        ) or None
        filters["technology"] = col3.text_input("Technology", placeholder="Node.js")
        year_text = col4.text_input("Year", placeholder="2025")
        filters["year"] = int(year_text) if year_text.strip().isdigit() else None

    submitted = st.button("Ask CareerOS", type="primary", use_container_width=True)
    if not submitted:
        return
    if not query or not query.strip():
        st.warning("Enter a question first.")
        return

    try:
        with st.spinner("Retrieving sources and generating a cited answer…"):
            result = run_query(
                query=query.strip(),
                mode=mode,
                job_description=job_description,
                filters=filters,
                include_debug=True,
            )
        render_query_result(result)
    except BackendError as exc:
        st.error(f"Request failed: {exc}")
    except httpx.ConnectError:
        st.error(
            f"Could not reach the CareerOS backend at `{BACKEND_URL}`. "
            "Is the stack running? Try `docker compose up --build`."
        )
    except httpx.TimeoutException:
        st.error("The request timed out. The local LLM may still be loading — try again.")


def page_explore_projects() -> None:
    st.header("🗂️ Explore Projects")
    st.caption(
        "Project and hackathon cards parsed directly from the indexed source documents."
    )
    try:
        with st.spinner("Loading projects…"):
            projects = api_get("/projects")
    except BackendError as exc:
        st.error(f"Could not load projects: {exc}")
        return
    except httpx.ConnectError:
        st.error(f"Backend unreachable at `{BACKEND_URL}`.")
        return

    if not projects:
        st.warning("No project documents are available. Check data/sample_docs/.")
        return

    for project in projects:
        with st.container(border=True):
            kind = project.get("document_type", "project").replace("_", " ").title()
            st.markdown(f"### {project.get('name', '')}")
            st.caption(f"{project.get('subtitle', '')} · {kind}")
            st.markdown(project.get("description", ""))

            technologies = project.get("technologies") or []
            if technologies:
                st.markdown("**Technologies**")
                st.markdown("  ".join(f"`{tech}`" for tech in technologies))

            themes = project.get("engineering_themes") or []
            if themes:
                st.markdown("**Engineering themes**")
                for theme in themes:
                    st.markdown(f"- {theme}")

            citation = project.get("citation") or {}
            st.caption(
                f"Source: `{citation.get('source_file', '')}` → "
                f"**{citation.get('section', '')}**"
            )
            if citation.get("quote"):
                st.markdown(f"> {citation['quote']}")

            if st.button(
                f"Ask about {project.get('name', 'this project')}",
                key=f"ask_{project.get('source_file', '')}",
            ):
                st.session_state["ask_query"] = f"What is {project.get('name', '')}?"
                st.session_state["nav_page"] = PAGE_ASK
                st.rerun()


def page_tailor_for_job() -> None:
    st.header("🎯 Tailor for a Job")
    st.caption(
        "Matches verified experience against a job description. Unverified requirements "
        "are called out explicitly — nothing is exaggerated."
    )

    target_role = st.text_input(
        "Target role", placeholder="e.g. Backend Engineering Intern"
    )
    job_description = st.text_area(
        "Job description",
        height=260,
        placeholder="Paste the complete job description…",
    )
    output_format = st.selectbox(
        "Output format",
        [
            "Match overview + skills + projects + bullets (tailor_resume)",
            "Skill-gap analysis (skill_gap)",
            "Resume bullets only (resume_bullets)",
        ],
    )
    extra_topics = st.text_input(
        "Extra focus (optional)", placeholder="e.g. AI tooling, REST API design"
    )

    if st.button("Generate tailored output", type="primary", use_container_width=True):
        if not job_description.strip() and "resume_bullets" not in output_format:
            st.warning("Paste a job description first.")
            return
        mode = "skill_gap" if output_format.startswith("Skill-gap") else (
            "resume_bullets" if output_format.startswith("Resume bullets") else "tailor_resume"
        )
        role_part = f" for the role of {target_role.strip()}" if target_role.strip() else ""
        query = f"Tailor Vedant Sawant's profile{role_part}."
        if extra_topics.strip():
            query += f" Extra focus: {extra_topics.strip()}."
        try:
            with st.spinner("Matching verified experience against the job description…"):
                result = run_query(
                    query=query,
                    mode=mode,
                    job_description=job_description.strip() or None,
                    include_debug=False,
                )
            render_query_result(result)
        except BackendError as exc:
            st.error(f"Request failed: {exc}")
        except httpx.ConnectError:
            st.error(f"Backend unreachable at `{BACKEND_URL}`.")
        except httpx.TimeoutException:
            st.error("The request timed out — try again once the local LLM is warm.")


def page_interview_preparation() -> None:
    st.header("🎯 Interview Preparation")
    st.caption(
        "Grounded practice questions and answer outlines built strictly from the "
        "indexed profile."
    )

    topic = st.selectbox(
        "Focus area",
        [
            "DevLens",
            "EnviroMonitor",
            "Apartment Visitor Security System",
            "GDG Hackathon",
            "SIES Hackathon",
            "Full profile",
        ],
    )
    custom = st.text_input(
        "Custom topic or question", placeholder="e.g. rate limiting and API security"
    )
    jd = st.text_area(
        "Optional: paste a job description to steer preparation",
        height=160,
    )

    if st.button("Generate interview prep", type="primary", use_container_width=True):
        focus = custom.strip() or topic
        query = (
            f"Generate interview preparation material about {focus}: likely questions, "
            "model answer outlines grounded in the sources, and talking points."
        )
        try:
            with st.spinner("Building grounded interview material…"):
                result = run_query(
                    query=query,
                    mode="interview_prep",
                    job_description=jd.strip() or None,
                    include_debug=True,
                )
            render_query_result(result)
        except BackendError as exc:
            st.error(f"Request failed: {exc}")
        except httpx.ConnectError:
            st.error(f"Backend unreachable at `{BACKEND_URL}`.")
        except httpx.TimeoutException:
            st.error("The request timed out — try again once the local LLM is warm.")


def page_about() -> None:
    st.header("ℹ️ About the System")

    st.markdown(
        """
**CareerOS** is a citation-grounded AI assistant for exploring Vedant Sawant's
projects, technical skills, hackathon experience, and software engineering profile.

### What is RAG?
**Retrieval-Augmented Generation (RAG)** answers a question in two steps:

1. **Retrieve** — the question is embedded as a vector and matched against
   indexed source chunks in Qdrant (with optional reranking).
2. **Generate** — only those chunks are passed to the LLM, which must ground
   every statement in them.

### Why citations?
Every factual answer carries **citation cards** (source file, section, chunk id,
and a supporting quote) so any claim can be verified against the original
document in seconds — in demos, interviews, or code review.

### How unsupported claims are prevented
- The system prompt forbids inventing technologies, metrics, awards, team
  sizes, employers, or seniority.
- Factual answers require `[n]` markers mapped to retrieved sources.
- When the index does not contain an answer, CareerOS replies: *"The indexed
  profile does not contain enough information to answer that accurately."*
- Verified experience and *current learning* are kept distinct, and
  recommendations are labeled as recommendations.

### Pipeline
`Markdown sources → structure-aware chunking → embeddings → Qdrant →
top-K retrieval → cross-encoder reranking → prompt builder → local LLM →
cited answer`

### Technologies used
FastAPI · Pydantic · Qdrant · sentence-transformers · cross-encoder reranker ·
OpenAI-compatible local LLM (Ollama) · Streamlit · Docker · pytest · Ruff
"""
    )

    st.subheader("Configuration status")
    try:
        status = api_get("/config/status")
        col1, col2 = st.columns(2)
        col1.metric("Environment", status.get("app_env", "n/a"))
        col2.metric("Collection", status.get("qdrant_collection", "n/a"))
        col3, col4 = st.columns(2)
        col3.metric("Embedding model", status.get("embedding_model", "n/a"))
        col4.metric("LLM model", status.get("llm_model", "n/a"))
        st.caption(
            f"Reranker: `{status.get('reranker_model', 'n/a')}` "
            f"({'enabled' if status.get('reranker_enabled') else 'disabled'}) · "
            f"top-k={status.get('top_k_retrieval')} · "
            f"top-n={status.get('top_n_reranked')} · "
            f"chunk={status.get('chunk_size')}/{status.get('chunk_overlap')}"
        )
    except Exception:  # noqa: BLE001 - informational only
        st.caption("Configuration status unavailable (backend not reachable).")

    st.subheader("Public links")
    try:
        profile = api_get("/profile")
        links = profile.get("links") or {}
        rendered = False
        for label, key in (("GitHub", "github"), ("LinkedIn", "linkedin"), ("Portfolio", "portfolio")):
            url = str(links.get(key, "")).strip()
            if url:
                st.markdown(f"- [{label}]({url})")
                rendered = True
        if not rendered:
            st.caption(
                "No public links configured. Set GITHUB_URL / LINKEDIN_URL / "
                "PORTFOLIO_URL in .env."
            )
        if profile.get("contact"):
            st.caption("Contact details are enabled by configuration.")
    except Exception:  # noqa: BLE001 - informational only
        st.caption("Profile links unavailable (backend not reachable).")

    st.subheader("Privacy notes")
    st.markdown(
        """
- Contact details (phone, personal email) are **hidden by default**
  (`SHOW_CONTACT_INFORMATION=false`).
- Queries are processed locally; no third-party analytics are embedded.
- The vector index only contains the public sample corpus in `data/sample_docs/`.
- Debug endpoints are disabled in production (`ENABLE_DEBUG_ENDPOINTS=false`).
"""
    )


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## CareerOS")
        st.caption(
            "A citation-grounded AI assistant for Vedant Sawant's engineering profile."
        )
        health = fetch_health()
        if health is None:
            st.warning("Backend unreachable")
        else:
            status = health.get("status", "unknown")
            icon = {"ok": "🟢", "degraded": "🟡"}.get(status, "🔴")
            st.caption(f"{icon} backend: {status} · v{health.get('version', '?')}")
        st.divider()
        page = st.radio("Navigate", PAGES, key="nav_page")
        st.divider()
        st.caption(
            "Every answer cites indexed sources. Unsupported questions get an "
            "explicit *not enough information* response."
        )
        return page


def main() -> None:
    st.set_page_config(
        page_title="CareerOS",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    page = render_sidebar()

    pages = {
        PAGE_ASK: page_ask_career_os,
        PAGE_PROJECTS: page_explore_projects,
        PAGE_TAILOR: page_tailor_for_job,
        PAGE_INTERVIEW: page_interview_preparation,
        "About the System": page_about,
    }
    pages.get(page, page_ask_career_os)()


if __name__ == "__main__":
    main()
