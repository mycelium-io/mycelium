---
name: generate-cli-docs
description: Regenerate the HTML CLI reference from @doc_ref decorators
user_invocable: true
---

Regenerate the CLI Reference section of the HTML docs site from `@doc_ref` decorators in the CLI codebase.

Steps:
1. Run: `cd mycelium-cli && uv run python ../docs/generate_cli_reference.py`
2. Report what was generated

If a CLI command was added or modified and doesn't have a `@doc_ref` decorator, add one:

```python
from mycelium.doc_ref import doc_ref

@doc_ref(
    usage="mycelium <group> <command> <args>",
    desc="One-line description. May contain <code>html</code>.",
    group="room",  # room, memory, message, or "other" for top-level
)
@app.command()
def my_command(...): ...
```

Then re-run the generator.
