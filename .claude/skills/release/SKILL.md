---
name: release
description: Cut a release — commit any staged changes, tag, create GitHub release, and optionally notify Webex. Use when the user says /release, /release --with-webex, or /release --preview.
argument-hint: "[--with-webex] [--preview]"
---

# Release

Commit latest changes (if any), tag, cut a GitHub release, and optionally notify Webex.

## Arguments

- `--with-webex` — after releasing, post a summary to Webex (default: `Mycelium Release Notes` only; add `--with-webex=eng` to also post to `IoC::Mycelium Eng`).
- `--preview` — cut a prerelease build for testing without affecting stable users. Skips Docker `:latest`, Homebrew, and ClawHub. Webex still gets a short preview ping (eng channel only — not user-facing release notes). Testers opt in via `mycelium upgrade --version <tag>`.

## Why preview releases are safe

The release pipeline's "promote to latest" steps (Docker `:latest` tags, GH "Latest" label, Homebrew formula, ClawHub) are gated on the tag matching a stable pattern. Tags containing `rc`, `alpha`, `beta`, or `preview` are detected as prereleases by the `detect-release-type` job in `.github/workflows/release.yml` and bypass all of those.

`install.sh` and `mycelium upgrade` both follow the GitHub `/releases/latest` redirect, which only resolves to releases NOT marked as prerelease. So stable users never see preview builds. Testers install with an explicit version pin.

## Steps

1. **Commit staged changes** — Run `git status`. If there are uncommitted changes, run /precommit checks then commit directly to main (admin push, no PR needed). Use a conventional commit message.

   **For `--preview`:** do NOT commit a `pyproject.toml` version bump to main. The release workflow seds the version in-place during the build only — main keeps tracking the next stable version, not the preview.

2. **Determine next tag** —
   - **Stable (`/release`):** Run `gh release list --limit 5` to find the current "Latest" release tag. Increment the patch version (e.g. `v1.0.0` → `v1.0.1`).
   - **Preview (`/release --preview`):** Find the latest stable tag (highest non-prerelease in `gh release list`). Target version is `<latest-stable-patch+1>`. Then check existing prereleases for that target: if `vX.Y.Zrc1` exists, cut `vX.Y.Zrc2`, etc. First preview for a target version is always `rc1`. Use PEP 440 format with no separator (`vX.Y.ZrcN`, NOT `vX.Y.Z-rc.N`) so the wheel filename matches what `install.sh` expects.

3. **Check for new migrations** — *Stable only.* Run:
   ```
   git diff <prev-stable-tag>..HEAD -- fastapi-backend/alembic_migrations/versions/
   ```
   If any new migration files exist, note this in the changelog and **include `mycelium migrate` in the upgrade instructions** in the Webex message (before `mycelium doctor`).

4. **Generate the CHANGELOG.md entry** — *Stable only. Skipped for `--preview`*: prerelease iterations get rolled up into the next stable's entry, not their own.

   No `[Unreleased]` block is maintained on `main`. Each release's section is derived from `git log <prev-stable-tag>..HEAD --no-merges --oneline` at release time. Group commits by conventional-commit prefix:

   - `feat:` → **Added**
   - `fix:` → **Fixed**
   - `refactor:`, `perf:`, `chore:`, dependency bumps, infra → **Changed**
   - revert / deletion commits → **Removed**

   Skip pure `docs:`, `style:`, `test:`, `ci:` commits unless they materially affect users. Reword each line to user-facing language (drop the prefix, keep PR links). Prepend the new section directly under the header preface — do NOT touch older entries.

   Commit the changelog update directly to `main` (admin push, no PR) with message `chore(release): changelog for <tag>`. **This commit must land before the tag is pushed** so the tag points at the commit that includes its own entry.

5. **Tag and push** — Run:
   ```
   git tag <new-tag> && git push origin <new-tag>
   ```
   The `release.yml` workflow detects whether the tag is a prerelease and gates the rest of the pipeline accordingly.

6. **Create GitHub release** — The `release.yml` workflow handles this automatically (via `softprops/action-gh-release`), including setting `prerelease: true` for preview tags. No manual `gh release create` needed.

   Wait for the workflow to finish (`gh run watch` or `gh run list --workflow=release.yml --limit 1`). If it fails, fix and re-run before posting any notifications.

7. **Webex notification** — Invoke `/webex` (no confirmation needed). Behavior depends on whether this is a stable or preview release.

   **Stable release** — when `--with-webex` is passed, post a bullet-point changelog summary with the tag and release URL. Each bullet should include the PR link if one exists (e.g. `- feat: description ([#123](https://github.com/mycelium-io/mycelium/pull/123))`). End the summary with a markdown link to the full changelog: `[Full changelog](https://github.com/mycelium-io/mycelium/blob/main/CHANGELOG.md)`. Follow with upgrade instructions using triple-backtick code blocks so they're copyable:
   ```
   To upgrade:
   mycelium upgrade && mycelium pull
   mycelium migrate              # if this release includes new migrations
   mycelium adapter add claude-code --reinstall  # if using claude-code
   mycelium adapter add cursor --reinstall        # if using cursor
   mycelium doctor  # to check health of services
   ```
   Include `mycelium migrate` only if step 3 found new migration files. Omit the line otherwise.
   Post to:
   - `Mycelium Release Notes` — always (room ID in `/webex` skill)
   - `IoC::Mycelium Eng` — only if `--with-webex=eng` was passed (room ID in `/webex` skill)

   **Preview release (`--preview`)** — post a short eng-only ping to `IoC::Mycelium Eng` (NOT `Mycelium Release Notes` — that channel is user-facing). No changelog. Use `--markdown` so the code blocks render. Just the tag, the GH release URL, and the install/upgrade commands testers need:
   ```
   Preview build cut: <tag>
   <release-url>

   Test on a fresh server:
   ```bash
   MYCELIUM_VERSION=<tag-without-v> curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
   mycelium pull --version <tag-without-v>
   ```

   Or upgrade in place:
   ```bash
   mycelium upgrade --version <tag-without-v>
   mycelium pull --version <tag-without-v>
   ```

   Roll back:
   ```bash
   mycelium upgrade --version <previous-stable>
   mycelium pull --version latest
   ```
   ```
   `mycelium pull --version <tag>` is the critical second step — it pins both `mycelium-backend` and `mycelium-db` images via `MYCELIUM_IMAGE_TAG` in `~/.mycelium/.env`. Without it, the new CLI runs against stale stable containers. Stable users are unaffected — `install.sh` and `mycelium upgrade` (no `--version`) still resolve to the latest stable, and `mycelium pull` (no `--version`) still pulls `:latest`.

8. **Mycelium patch notes** — Skipped for `--preview` (or scope to a `previews/<tag>` key if the user explicitly asks for it). Otherwise write the same changelog summary to the active Mycelium room:
   ```bash
   mycelium memory set "releases/<tag>" "<same bullet-point summary as Webex>" --handle claude-code-agent
   ```
   This keeps a persistent record of what shipped and when, visible to all agents sharing the room.
