---
name: release
description: Cut a release — commit any staged changes, tag, create GitHub release, and optionally notify Webex. Use when the user says /release or /release --with-webex.
argument-hint: "[--with-webex]"
---

# Release

Commit latest changes (if any), tag, cut a GitHub release, and optionally notify Webex.

## Arguments

- `--with-webex` — after releasing, post a summary to Webex (default: `Mycelium Release Notes` only; add `--with-webex=eng` to also post to `IoC::Mycelium Eng`)

## Steps

1. **Commit staged changes** — Run `git status`. If there are uncommitted changes, run /precommit checks then commit directly to main (admin push, no PR needed). Use a conventional commit message.

2. **Determine next tag** — Run `gh release list --limit 5` to find the current "Latest" release tag. Increment the patch version (e.g. `v1.0.0` → `v1.0.1`).

3. **Tag and push** — Run:
   ```
   git tag <new-tag> && git push origin <new-tag>
   ```

4. **Create GitHub release** — Run:
   ```
   gh release create <new-tag> --title "<new-tag>" --notes "<summary of changes since last tag>"
   ```
   Generate the release notes from `git log <prev-tag>..HEAD --oneline`.

5. **Webex notification** — If `--with-webex` was passed, invoke `/webex` (no confirmation needed) to post a bullet-point changelog summary with the tag and release URL, followed by upgrade instructions on a single line each:
   ```
   To upgrade:
   mycelium upgrade && mycelium pull
   mycelium adapter add openclaw --reinstall   # if using openclaw
   mycelium adapter add claude-code --reinstall  # if using claude-code
   mycelium doctor  # to check health of services
   ```
   Post to:
   - `Mycelium Release Notes` — always (room ID in `/webex` skill)
   - `IoC::Mycelium Eng` — only if `--with-webex=eng` was passed (room ID in `/webex` skill)

6. **Mycelium patch notes** — Write the same changelog summary to the active Mycelium room:
   ```bash
   mycelium memory set "releases/<tag>" "<same bullet-point summary as Webex>" --handle claude-code-agent
   ```
   This keeps a persistent record of what shipped and when, visible to all agents sharing the room.
