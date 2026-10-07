"""Answer generation with an OpenAI-compatible LLM (local by default).

Fallback behavior is a feature, not a failure mode:

* No relevant chunks → cautious "not enough information" answer.
* LLM unreachable / not configured → extractive answer assembled from the
  retrieved sources with ``[n]`` references, plus a warning in metadata.

The service therefore still runs (and tests still pass) without any LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings
from app.generation.context_formatter import format_context
from app.generation.prompts import build_messages
from app.retrieval.retriever import RetrievedChunk
from app.utils.text import first_sentence

logger = logging.getLogger(__name__)

INSUFFICIENT_INFO_ANSWER = (
    "The indexed profile does not contain enough information to answer that accurately."
)


class LLMUnavailableError(RuntimeError):
    """Raised when a chat completion could not be obtained."""


@dataclass
class GenerationResult:
    """Generated answer plus diagnostics for response metadata."""

    answer: str
    llm_model: str
    used_llm: bool = False
    warnings: list[str] = field(default_factory=list)


class AnswerGenerator:
    """Thin wrapper over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

    # ------------------------------------------------------------------
    @staticmethod
    def library_available() -> bool:
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def available(self) -> bool:
        return bool(self.settings.llm_base_url) and self.library_available()

    @property
    def _client_or_none(self):  # type: ignore[no-untyped-def]
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from openai import OpenAI
        except ImportError:  # pragma: no cover - guarded by `available`
            return None
        self._client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key_effective,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=1,
        )
        return self._client

    # ------------------------------------------------------------------
    def generate(
        self,
        mode: str,
        query: str,
        chunks: list[RetrievedChunk],
        job_description: str | None = None,
    ) -> GenerationResult:
        """Produce a grounded answer for ``query`` from ``chunks``."""
        if not chunks:
            return GenerationResult(
                answer=INSUFFICIENT_INFO_ANSWER,
                llm_model=self.settings.llm_model,
                used_llm=False,
                warnings=[
                    "No relevant sources were retrieved; returning the cautious fallback answer."
                ],
            )

        context_block = format_context(chunks)
        messages = build_messages(
            mode=mode,
            query=query,
            context_block=context_block,
            job_description=job_description,
        )

        client = self._client_or_none
        if client is None:
            answer = self._extractive_fallback(chunks)
            return GenerationResult(
                answer=answer,
                llm_model=self.settings.llm_model,
                used_llm=False,
                warnings=[
                    "LLM client unavailable (openai package missing or LLM_BASE_URL unset). "
                    "Returned an extractive answer built from retrieved sources."
                ],
            )

        try:
            response = client.chat.completions.create(
                model=self.settings.llm_model,
                messages=messages,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
            )
            answer = (response.choices[0].message.content or "").strip()
            if not answer:
                raise LLMUnavailableError("LLM returned an empty response.")
            return GenerationResult(
                answer=answer,
                llm_model=response.model or self.settings.llm_model,
                used_llm=True,
                warnings=[],
            )
        except Exception as exc:  # noqa: BLE001 - degrade instead of failing the request
            logger.warning("LLM generation failed (%s); using extractive fallback.", exc)
            return GenerationResult(
                answer=self._extractive_fallback(chunks),
                llm_model=self.settings.llm_model,
                used_llm=False,
                warnings=[
                    f"LLM call failed ({exc.__class__.__name__}). "
                    "Returned an extractive answer built from retrieved sources; "
                    "check LLM_BASE_URL, LLM_MODEL and that the local server is running."
                ],
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _extractive_fallback(chunks: list[RetrievedChunk]) -> str:
        """Deterministic, citation-tagged answer assembled from sources."""
        lines = [
            "*The configured LLM is unavailable, so this answer was assembled "
            "directly from the retrieved sources:*",
        ]
        for index, chunk in enumerate(chunks, start=1):
            excerpt = first_sentence(chunk.text, max_length=300)
            lines.append(f"{index}. [{index}] {chunk.title} — {chunk.section}: {excerpt}")
        lines.append("")
        lines.append(
            "Start the local LLM (see docs/deployment.md) for full natural-language answers."
        )
        return "\n".join(lines)
