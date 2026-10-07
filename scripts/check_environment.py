#!/usr/bin/env python3
"""Verify that the local environment can run CareerOS.

Checks (without mutating anything):
  * Python version (>= 3.11)
  * Required Python packages
  * Environment file presence and basic configuration
  * Docker availability (informational)
  * Backend / Qdrant reachability (informational)

Exit codes: 0 = ready, 1 = blocking problems, 2 = bad configuration.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
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

REQUIRED_MODULES = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("qdrant_client", "qdrant-client"),
    ("openai", "openai"),
    ("httpx", "httpx"),
    ("dotenv", "python-dotenv"),
]

OPTIONAL_MODULES = [
    ("sentence_transformers", "sentence-transformers (embeddings + reranker)"),
    ("streamlit", "streamlit (frontend)"),
    ("pytest", "pytest (tests)"),
    ("ruff", "ruff (linting)"),
    ("pypdf", "pypdf (PDF ingestion)"),
]

ok_lines: list[str] = []
warn_lines: list[str] = []
error_lines: list[str] = []

MIN_PYTHON = (3, 11)


def check_python() -> None:
    if sys.version_info[: len(MIN_PYTHON)] < MIN_PYTHON:
        error_lines.append(f"Python 3.11+ required, found {sys.version.split()[0]}")
    else:
        ok_lines.append(f"Python {sys.version.split()[0]}")


def check_modules() -> None:
    for module, label in REQUIRED_MODULES:
        if importlib.util.find_spec(module) is not None:
            ok_lines.append(f"Package available: {label}")
        else:
            error_lines.append(
                f"Missing package: {label} (pip install -r backend/requirements.txt)"
            )
    for module, label in OPTIONAL_MODULES:
        if importlib.util.find_spec(module) is not None:
            ok_lines.append(f"Package available: {label}")
        else:
            warn_lines.append(f"Optional package missing: {label}")


def check_env_files() -> None:
    example = ROOT / ".env.example"
    env_file = ROOT / ".env"
    if example.exists():
        ok_lines.append(".env.example present")
    else:
        error_lines.append(".env.example is missing")
    if env_file.exists():
        ok_lines.append(".env present")
    else:
        warn_lines.append(".env not found (optional — copy .env.example to .env to customize)")

    # Surface obvious misconfiguration without printing secret values.
    for key in ("QDRANT_URL", "LLM_BASE_URL", "BACKEND_URL", "API_PREFIX"):
        value = os.getenv(key, "")
        if value and not value.startswith(("http://", "https://")):
            error_lines.append(f"{key} must be an http(s) URL (value not printed)")
        elif value:
            ok_lines.append(f"{key} is set")
    if os.getenv("API_KEY") and os.getenv("API_KEY_ENABLED", "").lower() == "true":
        ok_lines.append("API_KEY_ENABLED=true with API_KEY set (value not printed)")


def check_docker() -> None:
    if shutil.which("docker") is None:
        warn_lines.append("Docker CLI not found — required for `docker compose up --build`")
    else:
        ok_lines.append("Docker CLI available")


def check_services() -> None:
    try:
        import httpx
    except ImportError:
        return

    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")

    # Inside Docker, BACKEND_URL points at the backend service name, which is
    # not resolvable from the host — only probe literal host URLs.
    for label, url, path in (
        ("Backend", backend_url, "/health"),
        ("Qdrant", qdrant_url, "/readyz"),
    ):
        if "backend" in url and url.startswith("http://backend"):
            warn_lines.append(f"{label} URL uses the Docker service name — not probed from host")
            continue
        try:
            response = httpx.get(f"{url}{path}", timeout=3)
            if response.status_code < 500:
                ok_lines.append(f"{label} reachable at {url} (HTTP {response.status_code})")
            else:
                warn_lines.append(f"{label} responded with HTTP {response.status_code} at {url}")
        except Exception:
            warn_lines.append(f"{label} not reachable at {url} (is the stack running?)")


def main() -> int:
    print("CareerOS environment check")
    print("=" * 60)
    check_python()
    check_modules()
    check_env_files()
    check_docker()
    check_services()

    for line in ok_lines:
        print(f"  [OK]   {line}")
    for line in warn_lines:
        print(f"  [WARN] {line}")
    for line in error_lines:
        print(f"  [FAIL] {line}")
    print("=" * 60)

    if error_lines:
        print("Blocking problems found — fix them before starting the stack.")
        return 1
    if warn_lines:
        print("No blocking problems. Warnings above are informational.")
        return 0
    print("Environment looks ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
