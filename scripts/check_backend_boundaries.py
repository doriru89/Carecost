#!/usr/bin/env python3
"""Lightweight backend architecture boundary checks.

This runs in "warn" mode by default to support gradual migration.
Use --strict to fail CI on violations.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "backend" / "app"
ROUTES_DIR = APP_DIR / "routes"
SERVICES_DIR = APP_DIR / "services"


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str


def _module_from_import(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        if not node.names:
            return None
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None


def _check_route_imports(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        mod = _module_from_import(node)
        if not mod:
            continue
        if mod.startswith("app.db") or mod.startswith("sqlalchemy"):
            violations.append(
                Violation(
                    path=path,
                    line=getattr(node, "lineno", 1),
                    message="Route layer should not import DB/SQLAlchemy directly.",
                )
            )
    return violations


def _check_service_imports(path: Path, tree: ast.Module) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        mod = _module_from_import(node)
        if not mod:
            continue
        if mod.startswith("app.routes"):
            violations.append(
                Violation(
                    path=path,
                    line=getattr(node, "lineno", 1),
                    message="Service layer should not import route modules.",
                )
            )
    return violations


def _collect_py_files(path: Path) -> list[Path]:
    return [p for p in path.rglob("*.py") if p.is_file()]


def run_checks() -> list[Violation]:
    violations: list[Violation] = []

    for path in _collect_py_files(ROUTES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_check_route_imports(path, tree))

    for path in _collect_py_files(SERVICES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_check_service_imports(path, tree))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check backend architecture boundaries")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail with non-zero exit code when violations are found.",
    )
    args = parser.parse_args()

    violations = run_checks()

    if not violations:
        print("backend-boundaries: no violations found")
        return 0

    print(f"backend-boundaries: found {len(violations)} violation(s)")
    for v in violations:
        rel = v.path.relative_to(ROOT)
        print(f"  - {rel}:{v.line} {v.message}")

    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
