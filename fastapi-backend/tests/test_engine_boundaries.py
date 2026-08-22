# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The room's core must not depend on any particular engine.

Engines are plugins: they install behaviour through the lifecycle bus and the
extension-point contracts, and the room's own machinery calls those contracts.
The direction matters — a core that imports a plugin is a plugin-shaped hard
dependency, and deleting the plugin takes the room down with it.

Two tests, because they fail differently. The static one proves nothing
*references* an engine, and catches a function-local import that reads as
decoupled at a glance. The runtime one proves the core doesn't *break* when an
engine is genuinely absent — the manual "delete the module and see" check, made
permanent.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

#: The room's own machinery: the summon path, the delivery queue, the channel.
#: These may import the lifecycle bus and the extension-point contracts, and
#: nothing that is one engine's implementation.
CORE_MODULES = [
    APP / "routes" / "participate.py",
    APP / "services" / "persister.py",
    APP / "services" / "room_channels.py",
]

#: First-party engines. ``main.py`` is the composition root and is *expected* to
#: import every one — that is where concrete plugins are allowed to be named.
ENGINE_MODULES = frozenset({"aligner", "synthesizer", "summonguard", "plan_sync"})


def _imported_names(path: Path) -> set[str]:
    """Every module name imported anywhere in ``path``, at any nesting depth.

    ``ast.walk`` rather than a scan of the module body: a function-local import
    is exactly the pattern that looks decoupled and isn't.
    """
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("path", CORE_MODULES, ids=lambda p: p.name)
def test_core_room_machinery_names_no_engine(path: Path):
    offenders = {
        name
        for name in _imported_names(path)
        if any(part in ENGINE_MODULES for part in name.split("."))
    }
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)} — the room's core must reach engines "
        "through app.services.engine_events / the extension-point contracts, never by name."
    )


def test_the_room_still_boots_with_every_guard_absent():
    """Block the guard's module outright and confirm the core is unaffected.

    Run in a subprocess so the import-blocking meta-path hook cannot leak into
    the rest of the suite.
    """
    program = textwrap.dedent("""
        import asyncio, sys

        class Blocker:
            def find_module(self, name, path=None):
                return self if name == "app.services.summonguard" else None
            def find_spec(self, name, path=None, target=None):
                if name == "app.services.summonguard":
                    raise ImportError("summonguard is not installed")
                return None

        sys.meta_path.insert(0, Blocker())

        # The core imports and the app builds with no guard in the tree...
        from app.main import app
        from app.services import summon_filter
        from app.routes import participate  # noqa: F401
        from app.services import persister  # noqa: F401

        # ...and an unguarded room decides exactly as it did before guards existed.
        ctx = summon_filter.SummonContext(
            room="r", message_id="m1", sender="avery",
            text="shipped it, credit to @alice", handles=("alice",),
        )
        assert asyncio.run(summon_filter.decide(ctx)) == {"alice": "wake"}
        assert asyncio.run(summon_filter.wakes("r", "m1", "alice")) is True

        try:
            import app.services.summonguard  # noqa: F401
        except ImportError:
            print("OK")
        else:
            raise AssertionError("the blocker did not take effect; test proves nothing")
    """)
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"core broke without the guard:\n{result.stderr[-3000:]}"
    assert "OK" in result.stdout
