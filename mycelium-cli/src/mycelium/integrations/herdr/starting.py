# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Starting an agent CLI in a herdr pane and waiting until it's ready.

The runner's launches (``runner/hosts.py``), its pane checks
(``runner/daemon.py``) and ``mycelium machine``'s restarts all start agents
through here, so a pane whose shell is slow to come up, an agent CLI that
exits before it's ready and one stopped at a first-run screen are handled the
same way everywhere.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from mycelium.integrations.agents import of_kind
from mycelium.integrations.herdr.bridge import (
    EXITED_DURING_START,
    NOT_A_SHELL,
    AgentExitedError,
    AgentNotReadyError,
    HerdrError,
    ShellNotReadyError,
    herdr_name,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: How many times, and how far apart, to try a start that failed for any
#: reason other than the pane's shell still starting.
START_ATTEMPTS = 3
START_RETRY_S = 1.5
#: How long a new pane's shell gets to reach its prompt. A login shell with a
#: heavy profile (nvm, conda, a prompt theme) can take many seconds.
SHELL_WAIT_S = 30.0
#: A start that took this long got as far as running the agent CLI, which
#: herdr then waited on: trying again would only wait again.
SLOW_START_S = 10.0
#: How long a shell may take before the person is told it's slow. A shell
#: usually reaches its prompt in a second or two; one still starting after
#: this is often stopped at something of its own (a question from its startup
#: files, a password) that only the person can see and answer in its terminal.
SLOW_SHELL_S = 5.0
#: How often a start herdr is still waiting on looks at the pane, to tell an
#: agent CLI that exited from one that's slow to come up.
EXIT_POLL_S = 1.0
#: How long a start may be in flight with no agent on its pane before the CLI is
#: taken to have exited. herdr names the agent on the pane the moment it takes
#: the start, and keeps it named until the agent is ready or gone; before
#: taking it, herdr's CLI waits at most 2s for the pane's shell, then answers.
EXIT_GRACE_S = 3.0


def _start_watched(bridge: Any, name: str, kind: str, pane: str, args: list[str] | None) -> None:
    """``bridge.start_agent``, failing as soon as the agent CLI exits.

    herdr waits out its whole timeout for an agent that exited before it came
    up: the agent's name goes with its process, so herdr is left waiting for a
    name that won't come back, and the start reads as hung for a minute. So the
    pane is looked at while herdr waits. An agent seen there and then gone has
    exited. So has one never seen once the start has been in flight past
    :data:`EXIT_GRACE_S`: a CLI refusing its arguments exits in a fraction of a
    second, before the first look. Either way :class:`AgentExitedError` says so
    at once. herdr's own start goes on in the background until its timeout,
    finding nothing.
    """
    done = threading.Event()
    failed: list[BaseException] = []

    def start() -> None:
        try:
            bridge.start_agent(name, kind, pane, agent_args=args)
        except BaseException as e:  # noqa: BLE001 - handed to the caller's thread as it is
            failed.append(e)
        finally:
            done.set()

    threading.Thread(target=start, name=f"start {name}", daemon=True).start()
    began = time.monotonic()
    seen = False
    while not done.wait(EXIT_POLL_S):
        try:
            agent = bridge.get_agent(pane)
        except HerdrError:
            continue
        if agent is not None:
            seen = True
        elif seen or time.monotonic() - began >= EXIT_GRACE_S:
            raise AgentExitedError(f"{kind} exited before it came up in pane {pane}")
    if failed:
        raise failed[0]


def start_when_ready(
    bridge: Any,
    handle: str,
    kind: str,
    pane: str,
    *,
    room: str,
    resume: str | None = None,
    on_slow_shell: Callable[[], None] | None = None,
) -> dict | None:
    """Start ``kind`` in ``pane``, giving a just-opened pane's shell time to come up.

    herdr names it for ``handle`` in ``room`` (:func:`herdr_name`), so a handle
    taken by an agent of another room here never blocks it. ``resume`` is a
    session to start it in, for a kind that can resume one.

    herdr starts an agent only in a pane sitting at its shell prompt, and a
    pane split a moment ago may still be starting its shell, so a start herdr
    refuses for that is tried again for up to ``SHELL_WAIT_S``. A start herdr
    reports as failed with an agent on the pane all the same (one stopped at a
    prompt never reads as ready) is not tried again, since a second start would
    find the name taken: that agent is returned, for the caller to read its
    state. ``None`` means it started and is ready. ``on_slow_shell`` is called
    once if the shell is still starting after ``SLOW_SHELL_S``.

    Raises :class:`ShellNotReadyError` when the shell never reached its prompt,
    :class:`AgentExitedError` when the agent CLI exited before it came up (not
    tried again: it would only exit again), :class:`AgentNotReadyError` when it
    ran but never came up as an agent, and :class:`HerdrError` for anything else.
    """
    known = of_kind(kind)
    args = known.launch_args() + ((known.resume_args(resume) or []) if resume else [])
    opened = time.monotonic()
    deadline = opened + SHELL_WAIT_S
    slow = False
    failures = 0
    while True:
        began = time.monotonic()
        try:
            _start_watched(bridge, herdr_name(room, handle), kind, pane, args or None)
        except AgentExitedError:
            raise
        except HerdrError as e:
            if EXITED_DURING_START in str(e):
                raise AgentExitedError(str(e)) from e
            if (agent := bridge.get_agent(pane)) is not None:
                return agent
            if time.monotonic() - began >= SLOW_START_S:
                raise AgentNotReadyError(str(e)) from e
            if NOT_A_SHELL in str(e):
                # Still waiting, but say so once it's slow: what holds a shell
                # up is on its screen, which is the person's to read, never
                # ours to parse.
                if on_slow_shell and not slow and time.monotonic() - opened >= SLOW_SHELL_S:
                    slow = True
                    on_slow_shell()
                if time.monotonic() >= deadline:
                    raise ShellNotReadyError(str(e)) from e
            else:
                failures += 1
                if failures >= START_ATTEMPTS:
                    raise
            time.sleep(START_RETRY_S)
        else:
            return None


def not_ready(kind: str, where: str) -> str | None:
    """Why agents of ``kind`` can't start ``where`` yet, as a launch says it; ``None``
    when nothing is known to be in the way.

    A CLI that would open on a first-run screen only the person can get past
    (Codex not signed in) is told before any pane opens, so a restart never
    starts an agent into a screen its prompt can't reach.
    """
    known = of_kind(kind)
    reason = known.not_ready()
    return f"{known.name} can't start {where} yet. {reason}" if reason else None


def start_unblocked(
    bridge: Any, handle: str, kind: str, pane: str, *, room: str, resume: str | None = None
) -> None:
    """:func:`start_when_ready`, refusing to go on past an agent waiting for input.

    That includes a first-run screen herdr reads as ready (Codex's welcome),
    after getting past any a key passes, and a first-run question the person
    answered by starting it in this folder (whether to trust it). The pane is
    left open: what it waits on is the person's to answer.
    """
    agent = start_when_ready(bridge, handle, kind, pane, room=room, resume=resume)
    passed: list[str] = []
    seen = bridge.past_first_run(pane, kind, passed)
    if seen:
        waiting = f"waiting there: {seen}"
    elif agent is not None and agent.get("agent_status") == "blocked" and not passed:
        waiting = "waiting for input there"
    else:
        return
    raise HerdrError(
        f"@{handle} started in pane {pane} but is {waiting}; "
        f"answer it (herdr agent focus {pane}) and start again"
    )
