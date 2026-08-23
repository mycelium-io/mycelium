# Mycelium docs source

The markdown here is the single source of truth for three surfaces: the
published site at [mycelium-io.github.io/mycelium](https://mycelium-io.github.io/mycelium/),
`mycelium docs` in the CLI, and `docs/llms-full.txt` for feeding the whole thing
to a model. Edit the markdown; never edit the generated HTML.

| Path | What lives here |
| --- | --- |
| `index.md` | What `mycelium docs` prints with no arguments |
| `overview.md` | The front door: what Mycelium is and why |
| `concepts/` | The model — rooms, memory, the board, episodes, the engines, L9 |
| `guides/` | Task-shaped walkthroughs, from quickstart to auth setup |
| `reference/` | Architecture and metrics |

A topic is addressed by its filename stem regardless of which folder holds it,
so `mycelium docs rooms` reads `concepts/rooms.md`. Moving a file between these
folders does not change its command.

## Changing a page

1. Edit the markdown.
2. Regenerate the site: `cd mycelium-cli && uv run python ../docs/generate_docs.py`
3. Commit both. CI fails if the generated output has drifted from the source.

New pages need an entry in `SECTION_CONFIG` in `docs/generate_docs.py` (which
page and sidebar group it belongs to) and in `SECTIONS` in
`mycelium-cli/src/mycelium/commands/docs.py` (its CLI topic name).
