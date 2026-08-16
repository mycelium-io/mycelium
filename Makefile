# Mycelium test targets.
#
# One command to validate a change without standing up the real stack. Every
# target here runs against local files + in-process fakes — no SLIM node, no Pi
# binary, no live LLM, no backend server. See fastapi-backend/tests/README.md and
# mycelium-cli/tests/README.md for how the fakes work.

.PHONY: help test test-backend test-cli test-frontend smoke lint client openapi

help:
	@echo "Targets:"
	@echo "  make test           Run the backend + CLI unit suites (node-free)"
	@echo "  make test-backend   Backend unit tests (fastapi-backend)"
	@echo "  make test-cli       CLI unit tests (mycelium-cli)"
	@echo "  make test-frontend  Frontend unit tests (mycelium-frontend, vitest)"
	@echo "  make smoke          Fast end-to-end happy-path over the fake stack"
	@echo "  make lint           Ruff + ty gate for backend and CLI"
	@echo "  make openapi        Refresh the openapi.json snapshot from the backend app"
	@echo "  make client         Regenerate the typed clients from openapi.json"

# The fast gate an agent runs before pushing: both Python unit suites.
test: test-backend test-cli

test-backend:
	cd fastapi-backend && uv run pytest tests/ -q

test-cli:
	cd mycelium-cli && uv run pytest tests/ -q

test-frontend:
	cd mycelium-frontend && pnpm test

# room -> engine -> await -> respond -> converge -> plan, all over fakes.
smoke:
	cd fastapi-backend && uv run pytest -m smoke -q

lint:
	cd fastapi-backend && uv run ruff check . && uv run ruff format --check . && uv run ty check .
	cd mycelium-cli && uv run ruff check . && uv run ruff format --check . && uv run ty check .

# The typed clients are build artifacts, not source: openapi.json is the
# committed spec, and both client trees are generated from it. Run `openapi`
# after changing a route or schema, then `client` to pick the change up.
openapi:
	scripts/snapshot-openapi.sh

client:
	scripts/gen-mycelium-client.sh
