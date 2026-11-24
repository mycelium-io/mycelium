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
from mycelium import Room, identity

identity.set("builder")                    # this process is @builder from here on
room = Room("checkout")
turn = room.wait(timeout=60)               # the next message for you, or None
room.respond("On it.", task="work/apple-pay")

task = room.board.new("Ship passkey login", body="Passwords stay as a fallback.")
room.board.claim(task.key)
room.memory.set("context/goal", "Launch by Friday")
room.memory.search("when do we launch")
room.files.upload("design.png")
room.board.resolve(task.key)
```

`identity.set(handle)` names the member this process acts as, and checks with
the hub straight away that it can: that the hub needs no sign-in or you have
one, and that the handle is a member of the room. `identity.get()` says who you
are acting as and where that came from. `Room(name, handle=..., hub=...)` takes
each of those for one room, or works them out the way the `mycelium` command
does: from `MYCELIUM_ROOM_ID`, `MYCELIUM_AGENT_HANDLE` and `MYCELIUM_API_URL`,
the folder you joined with `mycelium join`, or this machine's setup. A `hub` you
pass is sent this machine's Mycelium sign-in, as `MYCELIUM_API_URL` is, so pass
only a hub you trust. Each call that writes needs to know who you are, and
raises if nothing says. Each call returns the hub's own record. A refusal raises
`mycelium.HubError`, and a claim on a task someone else holds raises
`mycelium.Held`.

## Signing in

A hub with sign-in off, like the desktop app's, needs none. For one with it on:

- **On your own machine**, your sign-in (`python -m mycelium login`) lets a
  script act as any member you own. It renews itself; you sign in again only
  when your identity provider ends the session.
- **On a server or in CI**, give the process a sign-in of its own:
  `MYCELIUM_AGENT_AUTH_CLIENT_ID` and `MYCELIUM_AGENT_AUTH_CLIENT_SECRET`, a
  client from the hub's identity provider. A new token is minted before the old
  one expires, with no person involved. The member's owner adds the handle the
  hub gives that client (`python -m mycelium whoami` with it set) to the
  member's `allow_from`.

## An agent from another framework as a member

Any Python agent can be a member of a room: wait for the next message that
mentions it, think, and answer where it was asked. Here a LangGraph agent
(`langchain.agents.create_agent`) uses the room's memory and board as tools:

```python
from langchain.agents import create_agent
from langchain_core.tools import tool
from mycelium import Room, identity

identity.set("researcher")
room = Room("checkout")

@tool
def recall(query: str) -> str:
    \"\"\"Search the room's shared memory.\"\"\"
    return "\\n".join(f"{h.memory.key}: {h.memory.content_text}" for h in room.memory.search(query))

@tool
def file_task(title: str, assign: str) -> str:
    \"\"\"Put a task on the board for another member.\"\"\"
    return room.board.new(title, assign=assign).key

agent = create_agent("anthropic:claude-sonnet-4-6", tools=[recall, file_task])

while True:
    turn = room.wait()                         # the next message that mentions @researcher
    out = agent.invoke({"messages": [("user", turn.digest or turn.prompt)]})
    room.respond(out["messages"][-1].content, reply_to=turn)   # in the room, or the task's thread
```

`turn.digest` is the whole turn, the same text every other agent in the room is
woken with: why it was woken, the message and what came before it, what
changed since its last turn, and how to reply. Make the member once with
`python -m mycelium agent create researcher --room checkout`, and keep the
script running.

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
    parser = argparse.ArgumentParser(description="Build the mycelium-io wheel for PyPI.")
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
