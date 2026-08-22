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

Everything here is linted and type-checked, against the repo-root `ruff.toml`.
Run it from the repo root, exactly as CI does:

```bash
uv run --no-project --with ruff ruff check --config ruff.toml scripts
uv run --no-project --with ruff ruff format --check --config ruff.toml scripts
uv run --no-project --with ty ty check --python-version 3.12 scripts
```

`--no-project` is deliberate. A script here declares no dependencies — it is
standalone, run by hand from whatever environment has what it needs — so
checking it inside a neighbouring project's venv makes the answer depend on
which optional extras that project happens to pull in, and it stops matching
between CI and a laptop. Stdlib-only is the environment these scripts document,
so it is the one they are checked in.

The trade is that an import from outside the standard library is unresolvable
by construction; the three that exist (Pillow, Playwright, litellm) carry a
`# ty: ignore[unresolved-import]` at the import site saying so. Nothing type-
checks the *use* of those libraries, which is the honest cost of not pinning
a toolchain nobody needs in order to run the CI gates.
