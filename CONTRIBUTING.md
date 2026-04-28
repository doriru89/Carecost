# Contributing to CareCost

Thanks for your interest. This guide covers the basics for getting a dev environment running and submitting changes.

## Setup

1. **Clone** the repo and install dependencies:

   ```bash
   # Backend
   cd backend
   pip install -r requirements-dev.txt

   # Frontend
   cd ../frontend
   npm install
   ```

2. **PostgreSQL** — create two databases: `carecost` (dev) and `carecost_test` (tests).

3. **Environment** — copy the example files and fill in your local values:

   ```bash
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```

4. **Seed data** — run the import script to populate the database from CSVs in `data/`:

   ```bash
   python scripts/import_csv_to_postgres.py --az-mvp
   ```

5. **Run** — start the backend and frontend:

   ```bash
   cd backend && uvicorn app.main:app --reload --port 8001
   cd frontend && npm run dev
   ```

## Making changes

- Create a feature branch off `main`.
- Write tests for new behavior. Run the full suite before opening a PR:

  ```bash
  cd backend && pytest
  cd frontend && npm test
  ```

- Keep PRs focused — one feature or fix per PR.
- Update `backend/.env.example` if you add new environment variables.

## Migrations

Schema changes go through **Alembic**:

```bash
cd backend
alembic revision --autogenerate -m "description of change"
alembic upgrade head
```

Review the generated migration before committing — autogenerate is a starting point, not a guarantee.

## Code style

- **Backend**: Python 3.11+, formatted with `ruff`. Run `ruff check --fix` before committing.
- **Frontend**: TypeScript + React. Linted via ESLint (`npm run lint`).

## Questions

Open an issue or reach out to the team directly.
