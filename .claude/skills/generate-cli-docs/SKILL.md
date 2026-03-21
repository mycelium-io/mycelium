---
name: generate-cli-docs
description: Regenerate the HTML CLI reference from @doc_ref decorators
user_invocable: true
---

Regenerate the docs site (CLI Reference + content sections) from `@doc_ref` decorators and markdown source files.

Steps:
1. Run: `cd mycelium-cli && uv run python ../docs/generate_docs.py`
2. Report what was generated

If a CLI command was added or modified and doesn't have a `@doc_ref` decorator, add one:

```python
from mycelium.doc_ref import doc_ref

@doc_ref(
    usage="mycelium <group> <command> <args>",
    desc="One-line description. May contain <code>html</code>.",
    group="room",  # setup, room, memory, notebook, message, adapter, config, or "other"
)
@app.command()
def my_command(...): ...
```

Groups: setup, room, memory, notebook, message, adapter, config, other

Markdown source files live in `mycelium-cli/src/mycelium/docs/` and mirror the GUI docs.
The generator reads both @doc_ref decorators and markdown files to build `docs/index.html`.

Then re-run the generator.
