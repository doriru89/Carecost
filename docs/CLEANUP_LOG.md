# Cleanup Log

Track cleanup actions so deletions and moves are auditable.

## 2026-04-28

- Added architecture and testing standards docs:
  - `docs/ARCHITECTURE.md`
  - `docs/TESTING_STRATEGY.md`
- Added import-boundary scaffolding:
  - `scripts/check_backend_boundaries.py`
  - frontend ESLint boundaries for `src/features/**`
- Added regression tests for key flows:
  - backend auth/profile/provider/estimate integration contracts
  - frontend auth/profile route guard behavior
- Added quality dashboard scaffolding:
  - `frontend/src/pages/Quality.tsx`
  - `frontend/public/quality-status.json`
  - CI artifact generation hooks
- Added safety guardrails to prevent accidental production DB imports.
- Removed dead/unused files and stale assets:
  - `backend/app/db/models/user.py` (unused legacy Pydantic model)
  - `backend/app/services/provenance.py` (unused helper)
  - `backend/app/routes/me.py` (empty route file)
  - `scripts/demo-playwright.ts` (orphan one-off script, no references)
  - `scripts/generate_payment_table.py` (stale generator tied to removed `data/` layout)
  - `test-results/.last-run.json` (ephemeral artifact)
  - `frontend/public/videos/copy_6E9C5F6D-14D9-4DD6-97B0-8C00E2BDA1D7.MOV` (unused duplicate media file)
- Standardized remaining code/tests/docs to canonical `sample-data/` paths (removed stale root `data/` references).
- Tightened CI guardrails to strict mode:
  - backend boundary checks fail on violations
  - coverage thresholds fail CI when below target
- Added low-risk performance instrumentation:
  - cached settings loading (`lru_cache`)
  - request latency p50/p95 logging middleware on the API

## Pending cleanup candidates

- Evaluate `test-results/` tracked artifacts and keep only source-controlled fixtures.
- Continue moving legacy `frontend/src/lib` domain logic into feature-owned modules.
- Continue extracting backend route + DB coupling into module application layers.
