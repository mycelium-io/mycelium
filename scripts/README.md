# scripts

Maintainer utilities, run by hand. Nothing here is on the install path or in the
runtime — a user never executes these, and a broken one can sit unnoticed.

Three kinds live here:

- **Regenerators.** They refresh a committed artifact from a live source: the
  OpenAPI snapshot from a running backend, and the typed client from that
  snapshot. The generated output is committed, so the snapshot only tells the
  truth as of the last time someone ran the script. CI diffs the snapshot
  against a live backend to catch the gap.
- **Asset builders.** They render the banner and social images from fonts and
  ImageMagick. Their output is committed too, so you only need the toolchain if
  you're changing the image.
- **CI helpers.** `check_workflows.py` and `check_docs_links.py` are the
  exception to "run by hand" — they are gates, and they run locally the same
  way they run in CI (stdlib only, no install). The docs checker reports rather
  than fails; pass `--strict` to make it exit non-zero. `ci_timing.py` and
  `publish-screenshots.sh` read the Actions environment and only make sense on
  a runner.

Each script's header comment states its prerequisites and where its output
lands. Read that before running — several need a running backend or a font
installed, and fail unhelpfully without them.

Everything here is linted and type-checked. The rules are the repo-root
`ruff.toml` and the checks ride along in CI's `CLI lint + tests` job, where the
toolchain is already installed:

```bash
cd mycelium-cli
uv run ruff check --config ../ruff.toml ../scripts
uv run ruff format --check --config ../ruff.toml ../scripts
uv run ty check ../scripts
```
