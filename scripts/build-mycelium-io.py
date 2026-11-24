#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Build the ``mycelium-io`` wheel: the Python library, for PyPI.

The library is the CLI's own package (``from mycelium import Room``), so this
builds ``mycelium-cli`` under the name ``mycelium-io`` and without the
``mycelium`` command. Everything else (version, dependencies, package data)
is read from ``mycelium-cli/pyproject.toml`` as it stands, so the two can't
drift. Run it after the OpenAPI client is generated into
``mycelium-cli/src/mycelium_backend_client``, as the CLI's wheel is.

Usage:
    python scripts/build-mycelium-io.py [--out mycelium-cli/dist]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "mycelium-cli"

NAME = "mycelium-io"
DESCRIPTION = "Python library for Mycelium: rooms, tasks and memory for teams of agents"

#: The project's page on PyPI.
README = """\
# mycelium-io

The Python library for [Mycelium](https://github.com/mycelium-io/mycelium), where
people and agents work together in rooms: a board of tasks, a thread for each
task, and memory the whole room shares.

```python
from mycelium import Room

room = Room("checkout")                    # the hub, room and handle, as the CLI finds them
turn = room.wait(timeout=60)               # the next message for you, or None
room.respond("On it.", task="work/apple-pay")

task = room.board.new("Ship passkey login", body="Passwords stay as a fallback.")
room.board.claim(task.key)
room.memory.set("context/goal", "Launch by Friday")
room.memory.search("when do we launch")
room.files.upload("design.png")
room.board.resolve(task.key)
```

`Room(name, handle=..., hub=...)` takes each of those, or works them out the way
the `mycelium` command does: from `MYCELIUM_ROOM_ID`, `MYCELIUM_AGENT_HANDLE`
and `MYCELIUM_API_URL`, the folder you joined with `mycelium join`, or this
machine's setup. Each call returns the hub's own record. A refusal raises
`mycelium.HubError`, and a claim on a task someone else holds raises
`mycelium.Held`.

Requires Python 3.12 or newer.
"""


def as_library(pyproject: str) -> str:
    """The CLI's ``pyproject.toml`` with the library's name and no console script."""
    text, renamed = re.subn(r'(?m)^name = "mycelium-cli"$', f'name = "{NAME}"', pyproject)
    if renamed != 1:
        sys.exit('mycelium-cli/pyproject.toml has no `name = "mycelium-cli"` line to rename.')
    text = re.sub(r'(?m)^description = ".*"$', f'description = "{DESCRIPTION}"', text, count=1)
    # The [project.scripts] table, up to the next table.
    text, dropped = re.subn(r"(?ms)^\[project\.scripts\]\n.*?(?=^\[)", "", text)
    if dropped != 1:
        sys.exit("mycelium-cli/pyproject.toml has no [project.scripts] table to drop.")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CLI / "dist", help="where the wheel goes")
    out = parser.parse_args().out.resolve()

    if not (CLI / "src" / "mycelium_backend_client").is_dir():
        sys.exit(
            "Generate the OpenAPI client first: SPEC_FILE=openapi.json scripts/gen-mycelium-client.sh"
        )
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp) / NAME
        shutil.copytree(
            CLI / "src",
            build / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
        )
        (build / "README.md").write_text(README)
        (build / "pyproject.toml").write_text(as_library((CLI / "pyproject.toml").read_text()))
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=build, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
