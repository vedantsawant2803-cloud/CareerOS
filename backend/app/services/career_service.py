"""Career service: query answering, profile, and project exploration.

Profile and project data are parsed from the indexed source documents at
request time, so the API never hard-codes facts about the candidate — the
Markdown corpus remains the single source of truth.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.generation.citations import Citation, build_citations, citation_coverage
from app.generation.generator import AnswerGenerator
from app.ingestion.loaders import extract_title
from app.retrieval.retriever import RetrievalError, RetrievedChunk, Retriever
from app.services import BadRequestError, ServiceUnavailableError
from app.utils.text import first_sentence, is_bullet, split_paragraphs

logger = logging.getLogger(__name__)

PROJECT_TYPES = {"project", "hackathon"}

PROFILE_SECTIONS = (
    "professional profile",
    "technical skills",
    "selected projects",
    "relevant experience and achievements",
    "education",
    "engineering strengths",
)


class CareerService:
    """Answers career questions strictly from indexed context."""

    def __init__(
        self,
        settings: Settings,
        retriever: Retriever,
        generator: AnswerGenerator,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.generator = generator

    # ------------------------------------------------------------------
    def answer_query(
        self,
        query: str,
        mode: str = "qa",
        job_description: str | None = None,
        project: str | None = None,
        document_type: str | None = None,
        technology: str | None = None,
        year: int | None = None,
        include_debug: bool = False,
    ) -> dict:
        """Retrieve → generate → cite. Returns the API response payload."""
        from app.utils.timing import Timer

        with Timer() as timer:
            try:
                result = self.retriever.retrieve(
                    query=query,
                    project=project,
                    document_type=document_type,
                    technology=technology,
                    year=year,
                )
            except RetrievalError as exc:
                raise ServiceUnavailableError(str(exc)) from exc

            generation = self.generator.generate(
                mode=mode,
                query=query,
                chunks=result.chunks,
                job_description=job_description,
            )

        citations: list[Citation] = build_citations(result.chunks)
        coverage = citation_coverage(generation.answer, result.chunks)

        warnings = list(result.warnings) + list(generation.warnings)
        if generation.answer and "[1]" not in generation.answer and result.chunks:
            warnings.append("Generated answer contains no [n] citation markers.")

        return {
            "answer": generation.answer,
            "mode": mode,
            "citations": [citation.model_dump() for citation in citations],
            "retrieved_chunks": (
                [self._chunk_view(chunk) for chunk in result.chunks] if include_debug else []
            ),
            "metadata": {
                "retrieval_count": len(result.chunks),
                "latency_ms": timer.elapsed_ms,
                "llm_model": generation.llm_model,
                "confidence": result.confidence,
                "used_llm": generation.used_llm,
                "citation_coverage": coverage.coverage,
                "warnings": warnings,
            },
        }

    @staticmethod
    def _chunk_view(chunk: RetrievedChunk) -> dict:
        return {
            "rank": chunk.rank,
            "chunk_id": chunk.chunk_id,
            "text": chunk.text,
            "source_file": chunk.source_file,
            "title": chunk.title,
            "section": chunk.section,
            "document_type": chunk.document_type,
            "technologies": chunk.technologies,
            "year": chunk.year,
            "vector_score": round(chunk.vector_score, 4),
            "rerank_score": chunk.rerank_score,
        }

    # ------------------------------------------------------------------
    def get_profile(self) -> dict:
        """Structured public profile parsed from the resume + summary docs."""
        resume = self._load_markdown("vedant_resume.md")
        summary_doc = self._load_markdown("linkedin_summary.md")

        profile: dict = {
            "name": "Vedant Sawant",
            "title": "Software Engineer Intern",
            "location": "Dombivali, Maharashtra, India",
            "summary": "",
            "education": [],
            "skills": {},
            "engineering_strengths": [],
            "current_learning": [],
            "contact": None,
            "sources": [],
        }

        if resume:
            sections = resume["sections"]
            lowered = {key.lower(): value for key, value in sections.items()}
            profile["summary"] = lowered.get("professional profile", "").strip()
            skills = self._parse_skills(lowered.get("technical skills", ""))
            current = skills.pop("Currently learning", []) or skills.pop("Currently Learning", [])
            profile["skills"] = skills
            profile["engineering_strengths"] = self._bullets(
                lowered.get("engineering strengths", "")
            )
            profile["education"] = self._parse_education(lowered.get("education", ""))
            if not current:
                current = [
                    bullet
                    for bullet in self._bullets(lowered.get("technical skills", ""))
                    if "learning" in bullet.lower()
                ]
            profile["current_learning"] = current
            profile["sources"].append(
                {"source_file": resume["source_file"], "section": "Technical Skills"}
            )

        if summary_doc and not profile["summary"]:
            profile["summary"] = first_sentence(summary_doc["body"], max_length=600)

        if summary_doc:
            profile["sources"].append(
                {"source_file": summary_doc["source_file"], "section": "Profile"}
            )

        if self.settings.show_contact_information:
            profile["contact"] = {
                "email": "vedantsawant2803@gmail.com",
                "phone": "+91 9321805753",
            }

        profile["links"] = {
            "github": self.settings.github_url,
            "linkedin": self.settings.linkedin_url,
            "portfolio": self.settings.portfolio_url,
        }
        profile["public_profile_mode"] = self.settings.public_profile_mode
        return profile

    def get_projects(self) -> list[dict]:
        """Project and hackathon cards parsed from the source documents."""
        cards: list[dict] = []
        for source_file in self._project_files():
            document = self._load_markdown(source_file)
            if document is None:
                continue
            sections = document["sections"]
            lowered = {key.lower(): value for key, value in sections.items()}

            overview = lowered.get("overview", "") or lowered.get("contributions", "")
            cards.append(
                {
                    "name": document["title"],
                    "subtitle": document["subtitle"],
                    "document_type": document["document_type"],
                    "source_file": document["source_file"],
                    "technologies": self._parse_technologies(lowered.get("technologies", "")),
                    "description": first_sentence(overview, max_length=600)
                    or first_sentence(document["body"], max_length=600),
                    "engineering_themes": self._bullets(
                        lowered.get("engineering themes", "")
                        or lowered.get("recognition", "")
                        or lowered.get("outcome", "")
                    ),
                    "citation": {
                        "source_file": document["source_file"],
                        "document_type": document["document_type"],
                        "title": document["title"],
                        "section": self._first_section_name(sections) or "Overview",
                        "quote": first_sentence(overview or document["body"], max_length=240),
                    },
                }
            )
        return cards

    # ------------------------------------------------------------------
    def _project_files(self) -> list[str]:
        data_path = self.settings.data_path
        if not data_path.exists():
            return []
        files = []
        for path in sorted(data_path.glob("*.md")):
            name = path.name.lower()
            if name in {"vedant_resume.md", "linkedin_summary.md"}:
                continue
            files.append(path.name)
        return files

    def _load_markdown(self, file_name: str) -> dict | None:
        """Load a Markdown file and split it into heading-keyed sections."""
        path = self.settings.data_path / file_name
        if not path.exists():
            logger.warning("Source document missing: %s", path)
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        title = extract_title(text, Path(file_name).stem)
        sections, body, subtitle = self._split_sections(text)
        return {
            "source_file": file_name,
            "title": title,
            "subtitle": subtitle,
            "sections": sections,
            "body": body,
            "document_type": self._guess_type(file_name),
        }

    @staticmethod
    def _guess_type(file_name: str) -> str:
        name = file_name.lower()
        if "hackathon" in name:
            return "hackathon"
        if "resume" in name:
            return "resume"
        if "linkedin" in name or "summary" in name:
            return "profile"
        return "project"

    @staticmethod
    def _split_sections(text: str) -> tuple[dict[str, str], str, str]:
        """Return ``(sections_by_heading, plain_body, subtitle)``."""
        sections: dict[str, str] = {}
        current: list[str] = []
        current_heading = "(preamble)"
        body_lines: list[str] = []
        subtitle = ""
        seen_heading = False

        def flush() -> None:
            if current_heading and current:
                content = "\n".join(current).strip()
                sections.setdefault(current_heading, content)

        for line in text.splitlines():
            if line.startswith("# ") and not seen_heading:
                seen_heading = True
                body_lines = []
                continue
            if line.startswith("## ") or line.startswith("### "):
                flush()
                current = []
                current_heading = line.lstrip("#").strip()
                continue
            if not subtitle and not seen_heading:
                continue
            if not subtitle and line.strip():
                candidate = line.strip().strip("*").strip()
                if candidate and not candidate.startswith("#"):
                    subtitle = candidate
            current.append(line)
            body_lines.append(line)
        flush()
        return sections, "\n".join(body_lines).strip(), subtitle

    @staticmethod
    def _bullets(section_text: str) -> list[str]:
        items: list[str] = []
        for block in split_paragraphs(section_text or ""):
            if is_bullet(block.splitlines()[0]):
                for line in block.splitlines():
                    if is_bullet(line):
                        cleaned = line.strip()
                        cleaned = cleaned.lstrip("-*+").lstrip("0123456789.").strip()
                        if cleaned:
                            items.append(cleaned)
        return items

    @staticmethod
    def _parse_technologies(section_text: str) -> list[str]:
        bullets = CareerService._bullets(section_text)
        if bullets:
            return bullets
        return [part.strip() for part in section_text.replace("\n", ",").split(",") if part.strip()]

    @staticmethod
    def _parse_skills(section_text: str) -> dict[str, list[str]]:
        """Parse skills from `### Category` headings or `- **Category:** items` bullets."""
        import re

        skills: dict[str, list[str]] = {}
        category = "Skills"
        bold_category = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$")

        for raw_line in section_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("### "):
                category = line[4:].strip()
                skills.setdefault(category, [])
                continue
            if line.startswith("## "):
                category = line[3:].strip()
                skills.setdefault(category, [])
                continue
            bullet = line
            if is_bullet(line):
                bullet = line.lstrip("-*+").lstrip("0123456789.").strip()
            match = bold_category.match(bullet)
            if match:
                name = match.group(1).strip()
                remainder = match.group(2).strip()
                category = name
                skills.setdefault(category, [])
                if remainder:
                    if name.lower().startswith("currently learning"):
                        # Keep the learning phrase intact for the UI.
                        skills[category].append(remainder)
                    else:
                        for item in remainder.split(","):
                            cleaned = item.strip()
                            if cleaned:
                                skills.setdefault(category, []).append(cleaned)
                continue
            if is_bullet(line) and category and bullet:
                skills.setdefault(category, []).append(bullet)
        return {key: value for key, value in skills.items() if value}

    @staticmethod
    def _parse_education(section_text: str) -> list[dict]:
        entries: list[dict] = []
        for block in split_paragraphs(section_text or ""):
            entries.append({"text": " ".join(block.split())})
        return entries

    @staticmethod
    def _first_section_name(sections: dict[str, str]) -> str:
        for key in sections:
            if key != "(preamble)":
                return key
        return ""

    # ------------------------------------------------------------------
    def require_job_description(self, mode: str, job_description: str | None) -> None:
        """Defensive check shared with API validation."""
        if mode in {"tailor_resume", "skill_gap"} and not (job_description or "").strip():
            raise BadRequestError(f"mode='{mode}' requires a non-empty 'job_description' field.")
