#!/usr/bin/env python3
"""Export a demo snapshot of CareerOS data (profile, projects, health, sample answers).

Intended for portfolio demos and screenshot generation. The export never includes
contact details unless the backend has them explicitly enabled AND you pass
``--include-contact``.

Usage:
    python scripts/export_demo_data.py
    python scripts/export_demo_data.py --output exports/demo_data.json --sample-queries 3
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

DEFAULT_BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
DEFAULT_OUTPUT = ROOT / "exports" / "demo_data.json"

SAMPLE_QUERIES = [
    "Summarize Vedant's profile for a software engineering role.",
    "Which projects demonstrate backend engineering?",
    "What security-focused work has Vedant done?",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export CareerOS demo data.")
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--sample-queries", type=int, default=2)
    parser.add_argument(
        "--include-contact",
        action="store_true",
        help="Include contact details if the backend exposes them (off by default).",
    )
    return parser.parse_args(argv)


def safe_get(client: httpx.Client, url: str) -> dict | list | None:
    try:
        response = client.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return {"error": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend.rstrip("/")
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    export: dict = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": backend,
    }

    with httpx.Client() as client:
        try:
            health = client.get(f"{backend}/health", timeout=5)
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(
                f"Backend not reachable at {backend}: {exc}\n"
                "Start it with: docker compose up --build",
                file=sys.stderr,
            )
            return 2

        export["health"] = health.json()
        export["config_status"] = safe_get(client, f"{backend}/api/v1/config/status")
        export["profile"] = safe_get(client, f"{backend}/api/v1/profile")
        export["projects"] = safe_get(client, f"{backend}/api/v1/projects")

        if isinstance(export.get("profile"), dict) and not args.include_contact:
            export["profile"]["contact"] = None

        queries: list[dict] = []
        for question in SAMPLE_QUERIES[: max(args.sample_queries, 0)]:
            try:
                response = client.post(
                    f"{backend}/api/v1/query",
                    json={
                        "query": question,
                        "mode": "qa",
                        "job_description": None,
                        "filters": {
                            "project": None,
                            "document_type": None,
                            "technology": None,
                            "year": None,
                        },
                        "include_debug": True,
                    },
                    timeout=120,
                )
                if response.status_code == 200:
                    queries.append({"question": question, "response": response.json()})
                else:
                    queries.append({"question": question, "error": f"HTTP {response.status_code}"})
            except Exception as exc:  # noqa: BLE001
                queries.append({"question": question, "error": str(exc)})
        export["sample_queries"] = queries

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Demo data written to {output_path}")
    print(f"  profile fields  : {len(export.get('profile') or {})}")
    print(f"  projects        : {len(export.get('projects') or [])}")
    print(f"  sample queries  : {len(export['sample_queries'])}")
    if not args.include_contact:
        print("  contact details : excluded (default)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
