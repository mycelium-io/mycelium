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

2. **Determine next tag** — Run `git tag --sort=-v:refname | head -5` to find the latest `vX.Y.Z` tag. Increment the patch version (e.g. `v0.1.30` → `v0.1.31`).

3. **Tag and push** — Run:
   ```
   git tag <new-tag> && git push origin <new-tag>
   ```

4. **Create GitHub release** — Run:
   ```
   gh release create <new-tag> --title "<new-tag>" --notes "<summary of changes since last tag>"
   ```
   Generate the release notes from `git log <prev-tag>..HEAD --oneline`.

5. **Webex notification** — If `--with-webex` was passed, invoke `/webex` (no confirmation needed) to post a bullet-point changelog summary with the tag and release URL to:
   - `Mycelium Release Notes` (ID: `Y2lzY29zcGFyazovL3VzL1JPT00vYjBlYTY0YjAtMjQ3OS0xMWYxLTk3OTEtZmJlMDUzOTQzYzBl`) — always
   - `IoC::Mycelium Eng` (ID: `Y2lzY29zcGFyazovL3VzL1JPT00vZDgyOGQzYTAtYzU4Mi0xMWYwLThkNzMtM2ZhZTYyZTQ4ZjFj`) — only if `--with-webex=eng` was passed
