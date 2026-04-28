#!/usr/bin/env python3
"""Generate a machine-readable quality status document for /quality."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "frontend" / "public" / "quality-status.json"


def _read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _coverage_pct(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return round(val, 2)


def _read_backend_coverage(path: Path) -> float | None:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return None
    return _coverage_pct(totals.get("percent_covered"))


def _read_frontend_coverage(path: Path) -> float | None:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    total = data.get("total")
    if not isinstance(total, dict):
        return None
    lines = total.get("lines")
    if not isinstance(lines, dict):
        return None
    return _coverage_pct(lines.get("pct"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate quality dashboard status JSON")
    parser.add_argument("--backend-coverage", default=str(ROOT / "backend" / "coverage-backend.json"))
    parser.add_argument(
        "--frontend-coverage",
        default=str(ROOT / "frontend" / "coverage" / "coverage-summary.json"),
    )
    parser.add_argument("--status", default="unknown")
    parser.add_argument("--sha", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--failing-tests", default="")
    args = parser.parse_args()

    backend_pct = _read_backend_coverage(Path(args.backend_coverage))
    frontend_pct = _read_frontend_coverage(Path(args.frontend_coverage))

    failing_tests = [t for t in args.failing_tests.split(",") if t.strip()] if args.failing_tests else []

    out = {
        "status": args.status,
        "backendCoveragePct": backend_pct,
        "frontendCoveragePct": frontend_pct,
        "failingTests": failing_tests,
        "sha": args.sha,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote quality status to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
