---
name: precommit
description: Run precommit checks (lint, format, tests) on the mycelium codebase. Use when the user says /precommit or wants to check code quality before committing.
---

# Precommit Checks

Run all quality checks on the mycelium codebase. Report issues without auto-fixing.

## Steps

1. **Lint** — Run `ruff check` on both packages:
   ```bash
   cd fastapi-backend && ruff check .
   cd mycelium-cli && ruff check .
   ```

2. **Format check** — Run `ruff format --check` on both:
   ```bash
   cd fastapi-backend && ruff format --check .
   cd mycelium-cli && ruff format --check .
   ```

3. **Tests** — Run pytest if tests exist:
   ```bash
   cd fastapi-backend && python -m pytest tests/ -x -q
   ```

4. **CLI docs check** — If any CLI command files were changed (`mycelium-cli/src/mycelium/commands/`), remind the user to run `/generate-cli-docs` to regenerate the HTML CLI reference. Check if any new commands are missing `@doc_ref` decorators.

5. **Report** — Summarize all issues found. Do NOT auto-fix anything. Just report what needs attention.

If everything passes, say so clearly.
