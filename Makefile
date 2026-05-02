.PHONY: generate check lint test setup

generate:
	python scripts/generate_frontend_registry.py

check:
	python scripts/generate_frontend_registry.py --check
	python scripts/check_backend_boundaries.py --strict

lint:
	cd backend && ruff check . && ruff format --check .

test:
	cd backend && pytest --tb=short -q
	cd frontend && npx vitest run

setup:
	git config core.hooksPath .githooks
	npx gitnexus analyze --skip-agents-md
