# Mycelium docs source

These markdown files are the source for three things: the docs site at
[mycelium-io.github.io/mycelium](https://mycelium-io.github.io/mycelium/),
`mycelium docs` in the CLI, and `docs/llms-full.txt`, the whole set in one
file for giving to a model. Edit the markdown here, not the generated HTML.

| Path | What's in it |
| --- | --- |
| `index.md` | What `mycelium docs` prints with no arguments |
| `overview.md` | What Mycelium is and why you'd use it |
| `concepts/` | Rooms, memory, the board, episodes, the engines, L9 |
| `guides/` | Step-by-step guides, from the quick start to setting up sign-in |
| `reference/` | Architecture and metrics |

A page's CLI name is its filename without `.md`, whichever folder it's in. So
`mycelium docs rooms` reads `concepts/rooms.md`, and moving a file to another
folder doesn't change its name.

## Changing a page

1. Edit the markdown.
2. Regenerate the site: `cd mycelium-cli && uv run python ../docs/generate_docs.py`
3. Commit both. CI fails if the generated site doesn't match the markdown.

A new page also needs an entry in `SECTION_CONFIG` in `docs/generate_docs.py`
(which page and sidebar group it goes in) and in `SECTIONS` in
`mycelium-cli/src/mycelium/commands/docs.py` (its name in the CLI).

Some sections of the site are written directly in HTML and kept as they are
when the site is regenerated (they're marked `<!-- keep -->`), such as the
overview at the top of `docs/index.html` and the adapter sections in
`docs/adapters.html`. Edit those in the HTML.
