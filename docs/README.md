# docs

The published docs site, plus the runbooks that don't belong in it.

No design or planning documents live here — see the convention in the repo root
`CLAUDE.md`. This directory describes what the code *does*, not what someone
intended it to do.

## Generated vs. authored

**Most of the HTML here is generated. Don't hand-edit it.**

- The markdown under `mycelium-cli/src/mycelium/docs/` is the source of truth for
  the site's prose, organized into `concepts/`, `guides/` and `reference/` so the
  tree also reads well browsed on GitHub. The CLI reference and configuration
  tables are generated from the decorators and the pydantic config schema, so
  they can't describe a flag that doesn't exist.
- `generate_docs.py` renders those into the per-section HTML pages,
  `search-index.js`, and `llms-full.txt`. The regeneration command is in the repo
  root `CLAUDE.md`.
- `search-index.js` backs the top-bar search. It is derived from the rendered
  HTML, not the markdown, so the hand-coded sections and the generated reference
  are searchable on the same terms as everything else.
- A few sections have no markdown source and are hand-coded HTML kept verbatim
  across regenerations. Those are the ones that *can* go stale without a test
  noticing, so treat them with the suspicion you'd give an old comment.

## Authored by hand

- `agents.md`: the setup runbook written for an agent to follow, not a human to
  read. It's fetched over HTTP by whoever is installing, so its URL is part of
  the public contract.
- The remaining top-level markdown: demo script, evaluation results, and
  operational runbooks.

## The thing to check first

Anything here that names a command, a flag, or a file path is a claim about
code that can change without this directory noticing. Anything describing a
*boundary* (who owns what, what talks to what) survives much longer. Prefer
writing the second kind.
