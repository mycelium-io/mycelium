---
name: precommit
description: Run precommit checks (lint, format, tests) on the mycelium codebase. Use when the user says /precommit or wants to check code quality before committing.
---

# Precommit Checks

Run all quality checks on the mycelium codebase. Auto-fix issues where possible.

## Steps

1. **Lint + format** — Fix lint and format issues automatically:
   ```bash
   cd fastapi-backend && uv run ruff check --fix . && uv run ruff format .
   cd mycelium-cli && uv run ruff check --fix . && uv run ruff format .
   ```

2. **Tests** — Run pytest:
   ```bash
   cd fastapi-backend && uv run pytest tests/ -x -q
   ```

3. **CLI docs** — If any CLI command files were changed (`mycelium-cli/src/mycelium/commands/`):
   - Ensure new commands have `@doc_ref` decorators
   - Run `/generate-cli-docs` to regenerate the HTML CLI reference
   - If markdown source files changed (`mycelium-cli/src/mycelium/docs/*.md`), also run `cd mycelium-cli && uv run python ../docs/generate_docs.py` to regenerate `docs/index.html`

4. **Docs consistency** — If any user-facing behavior changed (commands renamed, new features, API changes), grep for stale references and fix them in:
   - `docs/index.html` — main docs page
   - `docs/mycelium-dataflow.html` — scrolly presentation deck
   - `docs/demo-script.md` — live demo script
   - `README.md` — quickstart and overview
   - `mycelium-cli/src/mycelium/docs/` — built-in CLI docs
   - Adapter skills (`mycelium-cli/src/mycelium/adapters/*/skills/`)

5. **Report** — Summarize what was fixed and any remaining issues.
