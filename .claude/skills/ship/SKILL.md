---
name: ship
description: Ship changes — run precommit checks, commit, and optionally push. Use when the user says /ship or wants to commit and push their work.
---

# Ship

Run quality checks, commit, and optionally push.

## Steps

0. **Branch check** — Run `git branch --show-current`. If on `main` or `master`, create a feature branch (`git checkout -b <descriptive-name>`) before proceeding.

1. **Precommit** — Run the /precommit checks (lint, format, tests). If any fail, stop and report.

2. **Review changes** — Run `git diff --stat` and `git status` to show what will be committed.

3. **Stage** — Stage relevant files. NEVER stage `.env`, credentials, or secrets. Use specific file paths, not `git add -A`.

4. **Commit** — Create a commit with a conventional commit message:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `refactor:` for refactoring
   - `docs:` for documentation
   - `test:` for test changes
   - `chore:` for maintenance

5. **Push + PR** — Push and open a PR against main with `gh pr create`. Never force push.

6. **Watch checks** — Run `gh pr checks --watch --fail-fast` and report pass or fail when complete.
