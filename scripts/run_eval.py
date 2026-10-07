#!/usr/bin/env python3
"""Run the CareerOS evaluation harness.

Computes retrieval and answer-quality metrics over ``data/eval/questions.json``.

Metrics (see docs/evaluation.md):
  * retrieval_hit_rate        — questions where at least one chunk was retrieved
  * expected_source_hit_rate  — questions whose answer cited an expected source
  * expected_source_recall    — average share of expected sources cited
  * citation_coverage         — average share of retrieved chunks cited in answers
  * point_coverage            — average share of expected points found in answers
  * response_length           — average answer length (words / characters)
  * faithfulness / relevance  — computed ONLY when an LLM judge is configured
                                (JUDGE_BASE_URL + JUDGE_MODEL); otherwise reported
                                as "not_computed" rather than fabricated.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --backend http://localhost:8000 --limit 5
    python scripts/run_eval.py --fail-under 0.6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (str(ROOT), str(ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import httpx  # noqa: E402

DEFAULT_BACKEND = os.getenv("EVAL_BACKEND_URL", "http://localhost:8000")
DEFAULT_DATASET = ROOT / "data" / "eval" / "questions.json"
DEFAULT_OUTPUT = ROOT / "exports" / "eval_report.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate CareerOS retrieval and answers.")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="Backend base URL")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Questions JSON path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Report output path")
    parser.add_argument("--limit", type=int, default=0, help="Evaluate only the first N questions")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit non-zero when mean point coverage is below this value (0-1)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("EVAL_TIMEOUT_SECONDS", "120")),
        help="Per-request timeout in seconds",
    )
    return parser.parse_args(argv)


def load_questions(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"No questions found in {path}")
    return questions


def contains_point(answer: str, point: str) -> bool:
    return point.lower() in answer.lower()


def run_one(client: httpx.Client, backend: str, entry: dict, timeout: float) -> dict:
    payload = {
        "query": entry.get("question", ""),
        "mode": entry.get("mode", "qa"),
        "job_description": entry.get("job_description"),
        "filters": {
            "project": None,
            "document_type": None,
            "technology": None,
            "year": None,
        },
        "include_debug": True,
    }
    started = datetime.now(UTC)
    response = client.post(f"{backend.rstrip('/')}/api/v1/query", json=payload, timeout=timeout)
    elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1000
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = response.text[:200]
        return {
            "id": entry.get("id"),
            "question": entry.get("question"),
            "answer": "",
            "error": f"HTTP {response.status_code}: {detail}",
            "retrieved": 0,
            "retrieval_hit": 0,
            "expected_source_hit": 0,
            "expected_source_recall": 0.0,
            "citation_coverage": 0.0,
            "point_coverage": 0.0,
            "answer_words": 0,
            "answer_chars": 0,
            "latency_ms": round(elapsed_ms, 2),
        }

    data = response.json()
    answer = data.get("answer", "")
    citations = data.get("citations", [])
    metadata = data.get("metadata", {})
    retrieved_chunks = data.get("retrieved_chunks", [])

    cited_sources = {citation.get("source_file") for citation in citations}
    expected_sources = set(entry.get("expected_sources", []))
    expected_points = entry.get("expected_points", [])

    source_recall = 0.0
    if expected_sources:
        source_recall = len(cited_sources & expected_sources) / len(expected_sources)

    point_hits = sum(1 for point in expected_points if contains_point(answer, point))
    point_coverage = (point_hits / len(expected_points)) if expected_points else 1.0

    has_citation_marker = "[" in answer and "]" in answer
    return {
        "id": entry.get("id"),
        "question": entry.get("question"),
        "answer": answer,
        "mode": payload["mode"],
        "error": None,
        "retrieved": len(retrieved_chunks),
        "retrieval_hit": 1 if retrieved_chunks else 0,
        "expected_source_hit": 1 if (cited_sources & expected_sources) else 0,
        "expected_source_recall": round(source_recall, 3),
        "citation_coverage": float(metadata.get("citation_coverage", 0.0)),
        "answer_has_citation_marker": has_citation_marker,
        "point_coverage": round(point_coverage, 3),
        "missing_points": [point for point in expected_points if not contains_point(answer, point)],
        "answer_words": len(answer.split()),
        "answer_chars": len(answer),
        "confidence": metadata.get("confidence"),
        "used_llm": metadata.get("used_llm"),
        "latency_ms": metadata.get("latency_ms", round(elapsed_ms, 2)),
        "warnings": metadata.get("warnings", []),
    }


def maybe_llm_judge(results: list[dict], answers: dict[str, str]) -> dict:
    """Optional LLM-as-judge faithfulness/relevance scoring.

    Runs only when JUDGE_BASE_URL and JUDGE_MODEL are set; otherwise returns
    explicit "not_computed" entries so no score is ever fabricated.
    """
    judge_base = os.getenv("JUDGE_BASE_URL", "").rstrip("/")
    judge_model = os.getenv("JUDGE_MODEL", "")
    if not judge_base or not judge_model:
        return {
            "faithfulness": (
                "not_computed (LLM judge unavailable: JUDGE_BASE_URL/JUDGE_MODEL unset)"
            ),
            "relevance": ("not_computed (LLM judge unavailable: JUDGE_BASE_URL/JUDGE_MODEL unset)"),
        }
    try:
        from openai import OpenAI
    except ImportError:
        return {
            "faithfulness": "not_computed (openai package unavailable)",
            "relevance": "not_computed (openai package unavailable)",
        }

    client = OpenAI(
        base_url=judge_base,
        api_key=os.getenv("JUDGE_API_KEY", "not-needed"),
        timeout=60,
    )
    faithful_scores: list[float] = []
    relevant_scores: list[float] = []
    for result in results:
        question = result.get("question") or ""
        answer = answers.get(str(result.get("id")), "")
        if not answer or result.get("error"):
            continue
        prompt = (
            "Rate the answer on two scales from 1 to 5.\n"
            f"Question: {question}\nAnswer: {answer}\n"
            'Return JSON only: {"faithfulness": <1-5>, "relevance": <1-5>}'
        )
        try:
            response = client.chat.completions.create(
                model=judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100,
            )
            text = (response.choices[0].message.content or "").strip()
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end == -1:
                continue
            scores = json.loads(text[start : end + 1])
            faithful_scores.append(float(scores["faithfulness"]))
            relevant_scores.append(float(scores["relevance"]))
        except Exception as exc:  # noqa: BLE001 - judge is best-effort
            print(f"  [WARN] judge failed for {result.get('id')}: {exc}", file=sys.stderr)

    def _mean(values: list[float]) -> float | str:
        return round(sum(values) / len(values), 3) if values else "not_computed"

    return {"faithfulness": _mean(faithful_scores), "relevance": _mean(relevant_scores)}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = ROOT / dataset_path

    try:
        questions = load_questions(dataset_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2
    if args.limit > 0:
        questions = questions[: args.limit]

    answers: dict[str, str] = {}
    results: list[dict] = []
    print(f"Evaluating {len(questions)} questions against {args.backend} ...")

    with httpx.Client() as client:
        # Fail fast with a clear message when the backend is not running.
        try:
            health = client.get(f"{args.backend.rstrip('/')}/health", timeout=5)
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(
                f"Backend not reachable at {args.backend}: {exc}\n"
                "Start the stack first: docker compose up --build",
                file=sys.stderr,
            )
            return 2

        for entry in questions:
            result = run_one(client, args.backend, entry, args.timeout)
            results.append(result)
            answers[str(result.get("id"))] = result.get("answer", "")
            marker = "ERR" if result.get("error") else "ok "
            print(
                f"  [{marker}] {result.get('id')} · "
                f"retrieved={result.get('retrieved')} · "
                f"src_hit={result.get('expected_source_hit')} · "
                f"points={result.get('point_coverage')}"
            )

    valid = [r for r in results if not r.get("error")]
    errored = [r for r in results if r.get("error")]
    count = len(valid) or 1

    metrics = {
        "questions_total": len(results),
        "questions_errored": len(errored),
        "retrieval_hit_rate": round(sum(r["retrieval_hit"] for r in valid) / count, 3),
        "expected_source_hit_rate": round(sum(r["expected_source_hit"] for r in valid) / count, 3),
        "expected_source_recall": round(sum(r["expected_source_recall"] for r in valid) / count, 3),
        "citation_coverage": round(sum(r["citation_coverage"] for r in valid) / count, 3),
        "point_coverage": round(sum(r["point_coverage"] for r in valid) / count, 3),
        "answer_citation_marker_rate": round(
            sum(1 for r in valid if r.get("answer_has_citation_marker")) / count, 3
        ),
        "response_length_words_mean": round(sum(r["answer_words"] for r in valid) / count, 1),
        "response_length_chars_mean": round(sum(r["answer_chars"] for r in valid) / count, 1),
        "latency_ms_mean": round(sum(float(r.get("latency_ms") or 0) for r in valid) / count, 1),
    }
    metrics.update(maybe_llm_judge(results, answers))

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": args.backend,
        "dataset": str(dataset_path),
        "metric_mode": "deterministic heuristics"
        if "not_computed" in str(metrics.get("faithfulness"))
        else "heuristics + LLM judge",
        "metric_definitions": {
            "retrieval_hit_rate": "share of questions where ≥1 chunk was retrieved",
            "expected_source_hit_rate": "share of questions citing ≥1 expected source",
            "expected_source_recall": "mean share of expected sources cited",
            "citation_coverage": "mean share of retrieved chunks referenced by [n] markers",
            "point_coverage": "mean share of expected points present in the answer",
            "answer_citation_marker_rate": "share of answers containing [n] markers",
        },
        "metrics": metrics,
        "results": results,
    }

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("-" * 60)
    print(f"{'metric':34} value")
    print("-" * 60)
    for key, value in metrics.items():
        print(f"{key:34} {value}")
    print("-" * 60)
    print(f"Report written to {output_path}")

    if errored:
        print(f"{len(errored)} question(s) returned errors (see report.results).")

    if args.fail_under is not None and metrics["point_coverage"] < args.fail_under:
        print(
            f"FAIL: point_coverage {metrics['point_coverage']} < threshold {args.fail_under}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
