#!/usr/bin/env python3
"""Coverage threshold checker with warn/default strict modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _backend_pct(path: Path) -> float | None:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        return None
    pct = totals.get("percent_covered")
    return float(pct) if pct is not None else None


def _frontend_pct(path: Path) -> float | None:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    total = data.get("total")
    if not isinstance(total, dict):
        return None
    lines = total.get("lines")
    if not isinstance(lines, dict):
        return None
    pct = lines.get("pct")
    return float(pct) if pct is not None else None


def _check(name: str, pct: float | None, threshold: float) -> tuple[bool, str]:
    if pct is None:
        return False, f"{name}: coverage not found"
    ok = pct >= threshold
    return ok, f"{name}: {pct:.2f}% (threshold {threshold:.2f}%)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check backend/frontend coverage thresholds")
    parser.add_argument("--backend-json", default="backend/coverage-backend.json")
    parser.add_argument("--frontend-json", default="frontend/coverage/coverage-summary.json")
    parser.add_argument("--threshold", type=float, default=75.0)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    backend = _backend_pct(Path(args.backend_json))
    frontend = _frontend_pct(Path(args.frontend_json))

    checks = [
        _check("backend", backend, args.threshold),
        _check("frontend", frontend, args.threshold),
    ]

    failures = [msg for ok, msg in checks if not ok]
    for ok, msg in checks:
        prefix = "PASS" if ok else "WARN"
        print(f"{prefix} {msg}")

    if failures and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
