---
name: generate-cli-docs
description: Regenerate the HTML docs site (CLI Reference, Configuration, content sections) from decorators, the pydantic config schema, and markdown source files
user_invocable: true
---

Regenerate the docs site from three sources:

- **CLI Reference** — generated from `@doc_ref` decorators on Typer commands
- **Configuration** — generated from `Field(..., description=...)` on the pydantic config schema in `mycelium-cli/src/mycelium/config.py`
- **Content sections** — generated from markdown files in `mycelium-cli/src/mycelium/docs/`

Steps:
1. Run: `cd mycelium-cli && uv run python ../docs/generate_docs.py`
2. Report what was generated

## Adding a new CLI command

If a CLI command was added or modified and doesn't have a `@doc_ref` decorator, add one:

```python
from mycelium.doc_ref import doc_ref

@doc_ref(
    usage="mycelium <group> <command> <args>",
    desc="One-line description. May contain <code>html</code>.",
    group="room",  # setup, room, memory, message, adapter, config, or "other"
)
@app.command()
def my_command(...): ...
```

Groups: setup, room, memory, message, adapter, config, other

## Adding a new config knob

Each pydantic field on a sub-model of `MyceliumConfig` becomes a row in the Configuration section of the docs. The only requirement is a non-empty `description=`:

```python
class NegotiationConfig(BaseModel):
    """Tunables for the CFN-mediated negotiation flow."""

    n_steps: int = Field(
        default=20,
        description=(
            "Maximum SAO rounds per session. Set to 0 to fall through to "
            "CFN's auto-computed budget."
        ),
    )
```

Whatever shows up in `description=` is what users will read. Spell it out — assume the reader doesn't know what SAO or CFN is. To add a brand new namespace:

1. Add a `<NewName>Config(BaseModel)` class with `Field(..., description=...)` on every field.
2. Wire it onto `MyceliumConfig` (e.g. `new_name: NewNameConfig = Field(default_factory=NewNameConfig)`).
3. Optionally add the namespace to `CONFIG_NAMESPACE_ORDER` in `docs/generate_docs.py` to control its position; otherwise it appends after the listed namespaces.
4. Re-run the generator.

The generator skips namespaces typed as bare `dict` (e.g. `adapters`) — see `CONFIG_NAMESPACE_SKIP`.

## Markdown source

Markdown files in `mycelium-cli/src/mycelium/docs/` are converted to HTML and embedded in the right `<section>` of `docs/index.html`. Sections in the existing HTML marked with `<!-- keep -->` are preserved verbatim (used for hand-crafted interactive components).

Then re-run the generator.
