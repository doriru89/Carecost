.PHONY: generate check lint test setup wiki lego serve test-docker

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

test-docker:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

setup:
	git config core.hooksPath .githooks
	npx gitnexus analyze --skip-agents-md

wiki:
	npx gitnexus wiki --model gemini-2.5-flash --base-url https://generativelanguage.googleapis.com/v1beta/openai --api-key $${GEMINI_API_KEY}

lego:
	python scripts/generate_lego_map.py

serve:
	npx gitnexus serve
