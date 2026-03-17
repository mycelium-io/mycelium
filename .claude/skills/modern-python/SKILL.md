---
name: modern-python
description: Modern Python tooling practices for the mycelium project. Use when installing dependencies, running tools, managing environments, or writing Python code. Always active as a background reference.
---

# Modern Python Practices

This project uses **uv** for package management, **ruff** for linting/formatting, and **pytest** for testing.

## Core Rules

| Do | Don't |
|----|-------|
| `uv add <pkg>` | Edit pyproject.toml deps manually |
| `uv add --group dev <pkg>` | `pip install <pkg>` |
| `uv sync --group dev` | `pip install -r requirements.txt` |
| `uv run pytest` | `python -m pytest` or bare `pytest` |
| `uv run ruff check .` | Bare `ruff check .` |
| `[dependency-groups]` for dev tools | `[project.optional-dependencies]` |
| `uv run python script.py` | `python script.py` (may use wrong env) |

## Quick Reference

```bash
# Install all deps (including dev)
uv sync --group dev

# Add a new dependency
uv add httpx
uv add --group dev pytest-cov

# Remove a dependency
uv remove some-package

# Run any tool through uv
uv run pytest tests/ -x -q
uv run ruff check .
uv run ruff format .
uv run python -c "import mycelium"

# Run with a temporary dep (not added to project)
uv run --with rich python -c "from rich import print; print('hello')"
```

## Project Structure

This project has two Python packages:

| Package | Path | Entry |
|---------|------|-------|
| **fastapi-backend** | `fastapi-backend/` | `app/main.py` |
| **mycelium-cli** | `mycelium-cli/` | `mycelium.cli:app` |

Each has its own `pyproject.toml`. Run `uv sync` from within each directory.

## Linting & Formatting

```bash
# Check (don't fix)
uv run ruff check .
uv run ruff format --check .

# Fix
uv run ruff check --fix .
uv run ruff format .
```

Ruff config is in each `pyproject.toml` under `[tool.ruff]`. We use `select = ["ALL"]` with explicit ignores.

## Testing

```bash
# Run tests
cd fastapi-backend && uv run pytest tests/ -x -q

# Run specific test
uv run pytest tests/test_memory.py -x -q

# Run with verbose output
uv run pytest tests/ -v
```

Tests use SQLite in-memory (see `tests/conftest.py`) — no Postgres needed for unit tests.

## Key Patterns

- **Python 3.12+** — we use modern syntax (X | Y unions, match/case if needed)
- **async/await** — FastAPI backend is fully async (asyncpg, AsyncSession)
- **Pydantic v2** — BaseModel with `model_config = {"from_attributes": True}`
- **Type hints** — always, but don't over-annotate obvious cases
- **`uv.lock`** — committed to version control for reproducible builds
