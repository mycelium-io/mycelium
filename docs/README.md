# docs

The published docs site, plus the design notes and runbooks that don't belong in
it.

## Generated vs. authored

**Most of the HTML here is generated. Don't hand-edit it.**

- The markdown under `mycelium-cli/src/mycelium/docs/` is the source of truth for
  the site's prose, organised into `concepts/`, `guides/` and `reference/` so the
  tree also reads well browsed on GitHub. The CLI reference and configuration
  tables are generated from the decorators and the pydantic config schema, so
  they can't describe a flag that doesn't exist.
- `generate_docs.py` renders those into the per-section HTML pages,
  `search-index.js`, and `llms-full.txt`. The regeneration command is in the repo
  root `CLAUDE.md`.
- `search-index.js` backs the top-bar search. It is derived from the rendered
  HTML, not the markdown, so the hand-coded sections and the generated reference
  are searchable on the same terms as everything else. It is written one record
  per line, and `.gitattributes` resolves it with git's union merge driver: two
  docs branches both regenerate the whole file, and as a single line that was a
  conflict no one could resolve by hand. Taking both sides can leave a record
  twice — a duplicated search hit, nothing worse — which the drift check in CI
  reports and regenerating fixes.
- A few sections have no markdown source and are hand-coded HTML kept verbatim
  across regenerations. Those are the ones that *can* go stale without a test
  noticing, so treat them with the suspicion you'd give an old comment.

## Authored by hand

- `agents.md`: the setup runbook written for an agent to follow, not a human to
  read. It's fetched over HTTP by whoever is installing, so its URL is part of
  the public contract.
- `design/`: decision records. These are dated arguments, not current-state
  docs: a design note describing a path not taken is still doing its job.
- The remaining top-level markdown: demo script, evaluation results, and
  operational runbooks.

## The thing to check first

Anything here that names a command, a flag, or a file path is a claim about
code that can change without this directory noticing. Anything describing a
*boundary* (who owns what, what talks to what) survives much longer. Prefer
writing the second kind.
