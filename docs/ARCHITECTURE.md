# CareCost Architecture

This document defines the current architecture, target architecture, and import boundaries used to keep the project modular.

## Current state

- Backend is organized mostly by technical layer under `backend/app/` (`routes`, `services`, `db`, `models`, `api`).
- Frontend is organized mostly by type under `frontend/src/` (`pages`, `components`, `lib`, `context`, `api`).
- This works for early velocity, but it creates coupling as the codebase grows.

## Target modular shape

### Backend (modular monolith)

Target root: `backend/app/modules/`

- `auth/`
- `providers/`
- `pricing/`
- `hospitals/`
- `assistant/`
- `shared/` (small shared kernel only)

Within each module:

- `api/` route handlers (thin transport layer)
- `application/` use-cases and orchestration
- `domain/` pure business rules (no FastAPI/SQLAlchemy imports)
- `infrastructure/` repositories and DB adapters
- `schemas/` DTOs

### Frontend (feature slices)

Target root: `frontend/src/features/`

- `auth/`
- `onboarding/`
- `map/`
- `estimate/`
- `profile/`
- `shared/` for reusable UI and utilities only

## Boundary rules

### Backend

- Route modules should not call SQLAlchemy models directly.
- Route modules should delegate to application/service layers.
- Domain code must not import FastAPI/SQLAlchemy.
- No `services -> routes` imports.

### Frontend

- Feature code may import from its own feature and from `shared`.
- Feature code should not import from other features directly.
- `shared` must stay generic and not import feature-specific modules.

## Enforcement

- Backend import checks are implemented by `scripts/check_backend_boundaries.py`.
- Frontend import scaffolding is implemented with ESLint rules in `frontend/eslint.config.js`.
- CI runs boundary checks in strict mode and fails on violations.

## Migration approach

- Move one module/feature at a time.
- Keep external API behavior stable while moving code.
- Add regression tests before each extraction step.
