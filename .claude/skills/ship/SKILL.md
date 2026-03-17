---
name: ship
description: Ship changes — run precommit checks, commit, and optionally push. Use when the user says /ship or wants to commit and push their work.
---

# Ship

Run quality checks, commit, and optionally push.

## Steps

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

   Show the proposed commit message and ask for confirmation before committing.

5. **Push** — Ask the user if they want to push. Only push if they confirm. Never force push.
