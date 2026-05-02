# CareCost — AI Agent Rules

> Structure and navigation: use GitNexus MCP (`npx gitnexus analyze --skip-agents-md`).
> This file defines behavioral constraints that can't be inferred from code.

## SSOT Rules
- All domain data lives in `data/registries/*.yaml` — NEVER hardcode
- Payer IDs, bundle IDs, hospital IDs, specialty names: import from `app.registries`
- Frontend consumes `frontend/src/generated/*.json` — never edit generated files directly
- After editing any `data/registries/*.yaml`, run: `python scripts/generate_frontend_registry.py`

## Architecture Boundaries (enforced by CI)
- Routes cannot import DB/SQLAlchemy
- Services cannot import routes
- Domain layers cannot import FastAPI/SQLAlchemy/DB
- Modules cannot import from other modules (only via `shared`)
- Verify: `python scripts/check_backend_boundaries.py --strict`

## Errata — Known Failure Patterns
Before writing code in these areas, check known patterns:
- CPT codes: ONLY from `data/registries/cpt_bundles.yaml` (never hardcode)
- Boundary bypass: don't import DB models in routes
- Test-endpoint mismatch: stale tests are real bugs, not pre-existing failures
- Registry staleness: generated JSON must match YAML source

## Tiers
**Always:** lint (`ruff`), test (`pytest`), registry freshness check, boundary check
**Ask First:** schema changes (Alembic), new modules, new registry entries
**Never:** hardcode CPTs/payers/hospitals, bypass registry, edit generated files, commit without tests

## Database Protocol
- Schema changes: always create Alembic migration on feature branch
- Merge conflict on migrations: `alembic merge heads`
- Never edit existing migration files
- Test cycle: upgrade → verify → downgrade → upgrade
- Production: `alembic upgrade head && uvicorn app.main:app`

## Commit Discipline
- Conventional commits, one logical change per commit
- Run `ruff check` + `ruff format --check` before committing
- Run `pytest` before pushing

## Setup
```bash
# AI codebase indexing
npx gitnexus analyze --skip-agents-md
# Claude Code MCP
claude mcp add gitnexus -- npx -y gitnexus@latest mcp
# Cursor
npx gitnexus setup
```
