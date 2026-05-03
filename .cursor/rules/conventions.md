# CareCost — AI Agent Conventions

> These rules apply to all AI-assisted code generation in this repository.
> Same source of truth as AGENTS.md, formatted for Cursor.

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

## Errata — Check Before Writing
Before modifying code in an area, read `.errata/patterns/` for known failure modes:
- `cpt-ssot-violation.yaml` — Never hardcode CPT codes
- `boundary-bypass.yaml` — Don't import DB models in routes
- `test-endpoint-mismatch.yaml` — Stale tests are real bugs
- `registry-staleness.yaml` — Generated JSON must match YAML
- `payer-id-slug-mismatch.yaml` — Backend IDs vs frontend slugs

## Tiers
**Always:** lint (`ruff`), test (`pytest`), registry freshness check, boundary check
**Ask First:** schema changes (Alembic), new modules, new registry entries
**Never:** hardcode CPTs/payers/hospitals, bypass registry, edit generated files, commit without tests

## Database Protocol
- Schema changes: always create Alembic migration on feature branch
- Merge conflict on migrations: `alembic merge heads`
- Never edit existing migration files
- Test cycle: upgrade → verify → downgrade → upgrade

## Testing
- Run full suite: `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit`
- Backend only: `cd backend && pytest --tb=short -q`
- Frontend only: `cd frontend && npx vitest run`

## Commit Discipline
- Conventional commits, one logical change per commit
- Run `ruff check` + `ruff format --check` before committing
- Run `pytest` before pushing
