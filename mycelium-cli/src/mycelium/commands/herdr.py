# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium herdr``: bind mycelium handles to persistent herdr agent panes.

herdr (https://herdr.dev) is an *optional* persistent-runtime layer: it keeps
coding-agent sessions alive and addressable across detach. mycelium coordinates
agents through rooms; herdr gives those agents a place to *live* so a
non-resident ``agent invoke`` has something to wake instead of queuing forever on
the durable cursor.

This group is the durable ``handle -> pane`` registry plus manual wake/inspect
commands. The registry is what turns herdr's ephemeral, exit-clearing agent names
into a stable mycelium binding. Auto-wake on ``agent invoke`` (opt-in via
``herdr.autowake``) reuses the same registry + bridge.

Everything is fail-soft: if herdr isn't installed or its server is down, these
commands say so and exit cleanly rather than erroring the way a hard dependency
would.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, NamedTuple

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from mycelium.cli_options import emits_json, in_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.integrations.herdr import (
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
    build_assigned_prompt,
    build_mention_prompt,
    build_wake_prompt,
    herdr_name,
    named_by_mycelium,
    session_of,
)
from mycelium.protocol import AgentManifest
from mycelium.runner.log import failing, ms, recovered, slow

if TYPE_CHECKING:
    import httpx

app = typer.Typer(
    help="Bind mycelium handles to persistent herdr agent panes (optional wake layer).",
    no_args_is_help=True,
)
console = Console()

#: How long one hub call in a sync pass may take, so a hub that never answers
#: is an error in the runner's log, not a pass that never ends.
HUB_TIMEOUT_S = 15.0
#: Wakes delivered, and hub calls that fail or are slow, in the runner's log.
_sync = logging.getLogger("mycelium.runner.sync")
_hub = logging.getLogger("mycelium.runner.hub")
#: Panes the sync pass left alone and said so, so it says it once, not every pass.
_left_alone: set[str] = set()
#: A pass's hub calls: one that hasn't connected or answered in this long is
#: tried again next pass rather than holding up every room's wakes.
PASS_TIMEOUT_S = 5.0
#: How long a member's manifest, once seen on the hub, is taken as still there.
MANIFEST_RECHECK_S = 600.0
#: How long a room the hub says it doesn't have is left out of the pass.
UNKNOWN_ROOM_S = 600.0
#: ``{(room, handle): monotonic time its manifest was last seen on the hub}``.
_manifest_seen: dict[tuple[str, str], float] = {}
#: ``{room: monotonic time to ask about it again}`` for rooms the hub doesn't have.
_unknown_rooms: dict[str, float] = {}


def _not_on_hub(room: str, resp: object) -> bool:
    """Whether ``resp`` says the hub has no such room; if so, leave it out for a while."""
    if getattr(resp, "status_code", None) != 404:
        return False
    if room not in _unknown_rooms:
        _sync.warning(
            "the hub has no room %s; leaving it out of the sync for %d minutes",
            room,
            UNKNOWN_ROOM_S // 60,
        )
    _unknown_rooms[room] = time.monotonic() + UNKNOWN_ROOM_S
    return True


def _left_out(room: str) -> bool:
    until = _unknown_rooms.get(room)
    if until is None:
        return False
    if until > time.monotonic():
        return True
    del _unknown_rooms[room]
    return False


def _bridge() -> HerdrBridge:
    return HerdrBridge()


@doc_ref(
    usage="mycelium herdr map <handle> <pane> [--room <room>] [--kind <kind>]",
    desc="Bind a mycelium handle to a herdr agent pane (e.g. w2:pV).",
    group="agent",
)
@app.command("map")
@in_room("room")
def herdr_map(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle (without leading @)."),
    pane: str = typer.Argument(..., help="herdr pane id hosting the agent, e.g. w2:pV."),
    room: str | None = None,
    kind: str | None = typer.Option(None, "--kind", help="herdr agent kind (claude, pi, …)."),
) -> None:
    """Record a durable ``handle -> pane`` binding used by wake.

    Validates the pane against herdr's live agent list when herdr is reachable
    (a warning, not a hard failure — you can map ahead of starting the agent).
    """
    try:
        room_name = str(room)
        bridge = _bridge()

        resolved_kind = kind
        if bridge.available():
            agent = bridge.get_agent(pane)
            if agent is None:
                console.print(
                    f"[yellow]Note:[/yellow] no live agent at pane [cyan]{pane}[/cyan] yet; "
                    "mapping saved; wake will re-check at call time."
                )
            else:
                resolved_kind = resolved_kind or agent.get("agent")
        else:
            console.print("[dim]herdr not reachable; saving mapping without validation.[/dim]")

        bridge.registry.set(
            HerdrPaneMapping(room=room_name, handle=handle, pane=pane, kind=resolved_kind)
        )
        console.print(
            f"[green]Mapped[/green] [cyan]@{handle.lstrip('@')}[/cyan] → "
            f"[cyan]{pane}[/cyan][dim] in {room_name}"
            + (f" ({resolved_kind})" if resolved_kind else "")
            + "[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr unmap <handle> [--room <room>]",
    desc="Remove a handle → pane binding.",
    group="agent",
)
@app.command("unmap")
@in_room("room")
def herdr_unmap(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle."),
    room: str | None = None,
) -> None:
    """Forget a ``handle -> pane`` binding."""
    try:
        room_name = str(room)
        removed = _bridge().registry.remove(room_name, handle)
        if removed:
            console.print(
                f"[green]Unmapped[/green] @{handle.lstrip('@')} [dim]in {room_name}[/dim]"
            )
        else:
            console.print(f"[yellow]No mapping[/yellow] for @{handle.lstrip('@')} in {room_name}")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage=(
        "mycelium herdr enroll [handle] [--room <room>] [--pane <id>] "
        "[--description <text>] [--owner <handle>]"
    ),
    desc="Join a room as the herdr agent in this pane, so mentions of it wake it.",
    group="agent",
)
@app.command("enroll")
@in_room("room")
def herdr_enroll(
    ctx: typer.Context,
    handle: str | None = typer.Argument(
        None, help="The handle to join as (default: from the pane's tab name)."
    ),
    room: str | None = None,
    pane: str | None = typer.Option(
        None, "--pane", help="herdr pane id (default: this pane, $HERDR_PANE_ID)."
    ),
    description: str | None = typer.Option(
        None, "--description", help="What this agent does, shown in the room's member list."
    ),
    owner: str | None = typer.Option(
        None, "--owner", help="Who it belongs to (default: this machine's person)."
    ),
) -> None:
    """Make the agent in this herdr pane a member of a room.

    For an agent running in a herdr pane that no workspace binding or runner
    enrolled: it registers the agent in the room and maps the pane, so a mention
    of it rings this pane. The mapping is a plain one, so no sync pass retires
    it. Its owner is this machine's person (`mycelium iam`), not the agent.
    Running it again in a pane that's already a member says so and changes
    nothing, unless --description or --owner is given, which updates just those.
    """
    import os

    from mycelium.client import typed_client
    from mycelium.commands.agent import (
        _load_manifest_remote,
        _remote_memory_text,
        _write_manifest,
    )

    def member(name: str) -> bool:
        """Whether the hub has anything at ``agents/<name>``, readable or not.

        A hub that can't be asked raises, so enroll says so rather than taking
        the handle as free or as taken.
        """
        with typed_client(config, timeout=HUB_TIMEOUT_S) as client:
            return _remote_memory_text(client, room_name, f"agents/{name}") is not None

    try:
        room_name = str(room)
        pane_id = pane or os.environ.get("HERDR_PANE_ID", "").strip()
        if not pane_id:
            console.print(
                "[red]Not in a herdr pane[/red] ($HERDR_PANE_ID isn't set). "
                "Run this inside the pane, or name it with --pane."
            )
            raise typer.Exit(1)
        bridge = _bridge()
        if not bridge.available():
            console.print("[red]herdr isn't reachable[/red], so the pane can't be checked.")
            raise typer.Exit(1)
        agent = bridge.get_agent(pane_id)
        if agent is None:
            console.print(f"[red]No agent is running in pane {escape(pane_id)}.[/red]")
            raise typer.Exit(1)

        config = MyceliumConfig.load()
        # The person whose machine this is owns the agent and is the one
        # registering it, whichever agent typed the command.
        whose = owner.lstrip("@") if owner else _owner(config)
        writer = whose or config.get_current_identity()
        mappings = [m for m in bridge.registry.all() if m.room == room_name]
        here = next((m for m in mappings if m.pane == pane_id), None)
        if here is not None:
            if not member(here.handle):
                manifest = _member_manifest(here.handle, room_name, agent, whose, description)
                _write_manifest(config, room_name, manifest, created_by=writer)
            elif description or owner:
                with typed_client(config, timeout=HUB_TIMEOUT_S) as client:
                    current = _load_manifest_remote(client, room_name, here.handle)
                if current is None:
                    console.print(
                        f"[red]agents/{escape(here.handle)} in {escape(room_name)} isn't a "
                        "manifest enroll can read[/red] (see `mycelium memory get "
                        f"agents/{escape(here.handle)} --room {escape(room_name)}`), so it's "
                        "left as it is."
                    )
                    raise typer.Exit(1)
                changes: dict[str, str] = {}
                if description:
                    changes["description"] = description
                if owner:
                    changes["owner"] = owner.lstrip("@")
                _write_manifest(
                    config, room_name, current.model_copy(update=changes), created_by=writer
                )
                console.print(
                    f"Updated @{escape(here.handle)}'s {' and '.join(changes)} in "
                    f"{escape(room_name)}."
                )
                return
            console.print(
                f"Already a member: [cyan]@{escape(here.handle)}[/cyan] in "
                f"{escape(room_name)}, pane {escape(pane_id)}."
            )
            console.print(_next_step(room_name))
            return

        taken = {m.handle for m in mappings}
        if handle:
            wanted = _sanitize_handle(handle.lstrip("@"), "")
            if not wanted:
                console.print(
                    f"[red]@{escape(handle)} can't be a handle:[/red] use lowercase "
                    "letters, digits, '.', '-' and '_'."
                )
                raise typer.Exit(1)
            if wanted in taken or member(wanted):
                console.print(
                    f"[red]@{wanted} is already a member of {escape(room_name)}.[/red] "
                    "Pick another handle."
                )
                raise typer.Exit(1)
        else:
            workspace = str(agent.get("workspace_id") or "")
            labels = bridge.tab_labels(workspace or None)
            wanted = _derive_handle(
                tab_label=labels.get(str(agent.get("tab_id") or ""), ""),
                pane_id=pane_id,
                prefix="",
                name_from="tab",
                taken=taken,
            )
            while member(wanted):
                wanted = _sanitize_handle(f"{wanted}-{_pane_suffix(pane_id)}", "") or (
                    f"agent-{_pane_suffix(pane_id)}"
                )

        manifest = _member_manifest(wanted, room_name, agent, whose, description)
        _write_manifest(config, room_name, manifest, created_by=writer)
        bridge.registry.set(
            HerdrPaneMapping(
                room=room_name,
                handle=wanted,
                pane=pane_id,
                kind=agent.get("agent"),
                cwd=agent.get("foreground_cwd") or agent.get("cwd"),
                session=session_of(agent),
            )
        )
        # Its herdr name says its handle in this room; only a label.
        try:
            bridge.rename_agent(pane_id, herdr_name(room_name, wanted))
        except HerdrError:
            pass
        console.print(
            f"[green]Joined[/green] {escape(room_name)} as [cyan]@{wanted}[/cyan]. "
            f"Mentions of @{wanted} now wake pane {escape(pane_id)}."
        )
        console.print(_next_step(room_name))
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


def _next_step(room: str) -> str:
    """What an agent that just joined does next. The app's introduction to an
    adopted agent names the same two commands, so both ways in say one thing."""
    return f"Next: run `mycelium skill print`, then `mycelium board --room {escape(room)}`."


def _room_members(config: MyceliumConfig, room_name: str) -> dict[str, str] | None:
    """The backend's live presence for a room: ``{handle: kind}`` (``slim``/``lease``).

    ``None`` if the backend is unreachable — so ``ls`` can distinguish "no lease"
    from "couldn't ask." Best-effort, mirrors ``agent._is_resident``.
    """
    import httpx

    from mycelium.client import auth_headers

    try:
        url = f"{config.server.api_url}/api/rooms/{room_name}/sessions/members"
        resp = httpx.get(url, timeout=5.0, headers=auth_headers(config))
        resp.raise_for_status()
        members = resp.json().get("members", [])
    except Exception:
        return None
    return {
        str(m.get("handle", "")).lstrip("@").lower(): str(m.get("kind") or "?") for m in members
    }


def _reconcile_note(mycelium_kind: str | None, herdr_status: str | None) -> tuple[str, str]:
    """The three-way verdict for one binding → ``(text, color)``.

    ``mycelium_kind`` is the backend presence kind (``slim``/``lease``/``None``);
    ``herdr_status`` is the live pane state (``None`` = pane empty / herdr blind).
    Flags the two disagreements that matter: a lease with no live pane (stale
    lease — the Finding-2 false positive) and a live pane the backend doesn't
    list (a herdr agent that isn't participating).
    """
    herdr_live = herdr_status in {"idle", "working", "blocked", "done"}
    if mycelium_kind in {"slim", "lease"} and not herdr_live:
        return ("⚠ stale lease", "red")
    if mycelium_kind is None and herdr_live:
        return ("herdr-only (not joined)", "yellow")
    if mycelium_kind in {"slim", "lease"} and herdr_live:
        return ("✓ in sync", "green")
    return ("-", "dim")


@doc_ref(
    usage="mycelium herdr ls [--room <room>]",
    desc="Reconcile handle → pane bindings: backend presence × live herdr state.",
    group="agent",
)
@app.command("ls")
@in_room("room", resolve=False)  # no room: every binding
@emits_json()
def herdr_ls(
    ctx: typer.Context,
    room: str | None = None,
) -> None:
    """Reconcile each binding across three views: the registry, the backend's
    presence (``slim``/``lease``), and herdr's live agent list.

    The backend runs containerized and is herdr-blind, so its presence lease can
    outlive an agent that has stopped looping ``await``. This is the one place
    that can cross-check — so a lease with a dead pane shows as **stale lease**,
    and a live herdr agent the backend never joined shows as **herdr-only**.
    """
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    try:
        config = MyceliumConfig.load()
        bridge = _bridge()
        mappings = bridge.registry.all()
        if room:
            mappings = [m for m in mappings if m.room == room]

        if not mappings:
            if as_json:
                typer.echo("[]")
                return
            console.print(
                "[dim]No herdr mappings. Bind one with `mycelium herdr map <handle> <pane>`.[/dim]"
            )
            return

        live: dict[str, str] = {}
        if bridge.available():
            for a in bridge.list_agents():
                pane = a.get("pane_id")
                if pane:
                    live[pane] = str(a.get("agent_status") or "unknown")

        # Backend presence, fetched once per distinct room in the view.
        members_by_room: dict[str, dict[str, str] | None] = {}
        for m in mappings:
            if m.room not in members_by_room:
                members_by_room[m.room] = _room_members(config, m.room)

        if as_json:
            rows = []
            for m in mappings:
                herdr_state = live.get(m.pane)
                members = members_by_room.get(m.room)
                myc_kind = members.get(m.handle.lower()) if members is not None else None
                rows.append(
                    {
                        "room": m.room,
                        "handle": m.handle,
                        "pane": m.pane,
                        "kind": m.kind,
                        "managed": m.managed,
                        # False when the hub couldn't be asked.
                        "presence_known": members is not None,
                        "mycelium": myc_kind,
                        "herdr": herdr_state,
                        "verdict": _reconcile_note(myc_kind, herdr_state)[0],
                    }
                )
            typer.echo(json.dumps(rows, indent=2, default=str))
            return

        table = Table(title="herdr ↔ mycelium reconciliation", show_lines=False)
        table.add_column("room", style="dim")
        table.add_column("handle", style="cyan")
        table.add_column("pane", style="cyan")
        table.add_column("mycelium")  # backend presence kind
        table.add_column("herdr")  # live pane state
        table.add_column("verdict")
        for m in mappings:
            herdr_status = live.get(m.pane)
            members = members_by_room.get(m.room)
            myc_kind = members.get(m.handle.lower()) if members is not None else None

            hcolor = {
                "idle": "green",
                "done": "green",
                "working": "yellow",
                "blocked": "red",
            }.get(herdr_status or "", "dim")
            note, ncolor = _reconcile_note(myc_kind, herdr_status)
            myc_display = "[dim]?[/dim]" if members is None else (myc_kind or "[dim]absent[/dim]")
            table.add_row(
                m.room,
                f"@{m.handle}",
                m.pane,
                myc_display,
                f"[{hcolor}]{herdr_status or '-'}[/{hcolor}]",
                f"[{ncolor}]{note}[/{ncolor}]",
            )
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


def _sanitize_handle(raw: str, prefix: str) -> str:
    """Coerce arbitrary text (a tab label / pane id) to the manifest handle rule.

    Handles must match ``^[a-z0-9][a-z0-9._-]*$``. Lowercase, collapse runs of
    invalid chars to a single ``-``, trim separators, cap length, prepend
    ``prefix``. Returns ``""`` if nothing usable survives (caller falls back).
    """
    s = re.sub(r"[^a-z0-9._-]+", "-", raw.strip().lower())
    s = re.sub(r"[-._]{2,}", "-", s).strip("-._")[:32].strip("-._")
    if not s:
        return ""
    cand = f"{prefix}{s}".lstrip("-._")
    return cand if re.match(r"^[a-z0-9][a-z0-9._-]*$", cand) else ""


def _pane_suffix(pane_id: str) -> str:
    """The stable, unique tail of a pane id (``w2:pV`` → ``pv``)."""
    return re.sub(r"[^a-z0-9]+", "", pane_id.split(":")[-1].lower()) or "x"


def _derive_handle(
    *, tab_label: str, pane_id: str, prefix: str, name_from: str, taken: set[str]
) -> str:
    """Pick a unique handle for a pane, preferring the tab name when asked.

    ``name_from='tab'`` uses the (meaningful) tab label, falling back to the pane
    id when the label is empty/unusable; ``'pane'`` always uses the pane id. On a
    collision within the batch (two tabs with the same name), the pane suffix is
    appended to keep handles unique — pane ids are unique by construction.
    """
    if name_from == "tab":
        # A tab Mycelium named lists the members in it, which is no name for another.
        base = "" if named_by_mycelium(tab_label) else _sanitize_handle(tab_label, prefix)
        if not base:  # unusable tab label → pane fallback, namespaced so it isn't bare
            base = _sanitize_handle(_pane_suffix(pane_id), prefix or "agent-")
    else:  # pane mode: the pane id with the caller's prefix (verbatim)
        base = _sanitize_handle(_pane_suffix(pane_id), prefix)
    if not base:
        base = f"agent-{_pane_suffix(pane_id)}"
    if base not in taken:
        return base
    disambiguated = _sanitize_handle(f"{base}-{_pane_suffix(pane_id)}", "")
    return disambiguated or f"{base}-{_pane_suffix(pane_id)}"


def _enroll_one(
    config: MyceliumConfig,
    bridge: HerdrBridge,
    room: str,
    agent: dict,
    *,
    taken: set[str],
    name_from: str,
    prefix: str,
    tab_labels: Callable[[], dict[str, str]],
    owner: Callable[[], str | None],
) -> str | None:
    """Ensure one live herdr agent is a member of ``room``; return its handle if
    this call newly enrolled it (``None`` if it was already bound or is left
    alone). ``owner`` and ``tab_labels`` are asked only for an agent no mapping
    has, so a quiet pass costs no lookup.

    Idempotency is keyed on the **pane**, not the derived handle: if any mapping
    in the room already points at this pane, the agent is already a member (we
    just re-materialize its manifest if it went missing). Only a genuinely new
    pane derives a fresh handle — collision-checked against the room's existing
    handles — and gets a manifest + a ``managed`` mapping.

    A member's manifest is the person's and the agent's to edit (its
    description, its owner), so a pass writes one only when the hub has none at
    all. One the hub has but can't parse is still theirs: rewriting it would
    throw away what they wrote.
    """
    from mycelium.commands.agent import _write_manifest

    def writer() -> str:
        return owner() or config.get_current_identity()

    pane = str(agent["pane_id"])
    existing = next((m for m in bridge.registry.all() if m.room == room and m.pane == pane), None)
    if existing is not None:
        # Already bound to this pane — heal a manifest that was deleted out from
        # under us so the member doesn't silently drop off the roster. Looked at
        # every few minutes, not every pass: a pass makes one call per room, not
        # one per agent.
        key = (room, existing.handle)
        seen = _manifest_seen.get(key)
        if seen is not None and time.monotonic() - seen < MANIFEST_RECHECK_S:
            return None
        there = _manifest_on_hub(config, room, existing.handle)
        if there is False:
            manifest = _member_manifest(existing.handle, room, agent, owner())
            _write_manifest(config, room, manifest, created_by=writer(), timeout=HUB_TIMEOUT_S)
        if there is not None:
            _manifest_seen[key] = time.monotonic()
        return None

    tab_label = tab_labels().get(str(agent.get("tab_id") or ""), "")
    if named_by_mycelium(tab_label):
        # Mycelium started the agents in this tab and mapped each one, so an
        # agent here that no mapping has is not a new member. Enrolling it made
        # a member named after the tab, its handles joined (`@a @b` -> `a-b`).
        if pane not in _left_alone:
            _left_alone.add(pane)
            _sync.info(
                "left alone the agent in %s: its tab %r is one Mycelium named, and no "
                "member is mapped to its pane",
                pane,
                tab_label,
            )
        return None

    handle = _derive_handle(
        tab_label=tab_label,
        pane_id=pane,
        prefix=prefix,
        name_from=name_from,
        taken=taken,
    )
    taken.add(handle)
    manifest = _member_manifest(handle, room, agent, owner())
    _write_manifest(config, room, manifest, created_by=writer(), timeout=HUB_TIMEOUT_S)
    bridge.registry.set(
        HerdrPaneMapping(
            room=room,
            handle=handle,
            pane=pane,
            kind=agent.get("agent"),
            managed=True,
            cwd=agent.get("foreground_cwd") or agent.get("cwd"),
        )
    )
    return handle


def _manifest_on_hub(config: MyceliumConfig, room: str, handle: str) -> bool | None:
    """Whether the hub holds anything at ``agents/<handle>``, readable or not.

    ``None`` when the hub couldn't be asked, which a caller must not read as
    "missing".
    """
    import httpx

    from mycelium.client import typed_client
    from mycelium.commands.agent import _remote_memory_text
    from mycelium_backend_client.errors import UnexpectedStatus

    try:
        with typed_client(config, timeout=HUB_TIMEOUT_S) as client:
            return _remote_memory_text(client, room, f"agents/{handle}") is not None
    except (httpx.HTTPError, UnexpectedStatus):
        return None


def _member_manifest(
    handle: str, room: str, agent: dict, owner: str | None, description: str | None = None
) -> AgentManifest:
    """The manifest for a herdr agent enrolled as ``handle``, saying which agent CLI it is."""
    from mycelium.integrations import AddOptions, adapter_for, get_integration

    kind = str(agent.get("agent") or "") or None
    manifest = get_integration(adapter_for(kind), cwd=agent.get("cwd")).build_manifest(
        handle=handle,
        opts=AddOptions(room=room),
        description=description or f"herdr-enrolled from {agent['pane_id']} ({kind})",
        allow_from=[],
        owner=owner,
    )
    return manifest.model_copy(update={"framework": kind})


def _owner(config: MyceliumConfig) -> str | None:
    """Who owns an agent this machine registers: its person, never the agent asking.

    ``None`` when the machine names no person. Falling back to the acting
    identity wrote the agent that ran the command (``mycelium-harness``) or the
    placeholder ``unknown`` as owner, and only an owner may pause or stop an
    agent, so "pause my agents" missed them.
    """
    from mycelium import caller

    return caller.person(config)


def _retire_one(config: MyceliumConfig, bridge: HerdrBridge, mapping: HerdrPaneMapping) -> None:
    """Remove a sync-managed member whose herdr pane is gone: deregister its
    manifest (notes/logs preserved) and drop the mapping. The teardown half of
    "herdr lifecycle *is* mycelium lifecycle."""
    from mycelium.commands.agent import _delete_manifest, _load_manifest

    manifest = _load_manifest(mapping.room, mapping.handle)
    if manifest is not None:
        _delete_manifest(config, mapping.room, manifest, timeout=HUB_TIMEOUT_S)
    bridge.registry.remove(mapping.room, mapping.handle)


def _reconcile_workspace(
    config: MyceliumConfig,
    bridge: HerdrBridge,
    workspace: str,
    room: str,
    *,
    name_from: str,
    prefix: str,
    kind: str | None,
) -> tuple[list[str], list[str]]:
    """Make ``room``'s membership equal the live agents in ``workspace``.

    Enrolls any live agent that isn't a member yet and retires any sync-managed
    member whose pane has closed (not one whose pane is open with no agent in
    it, which only stopped). Returns ``(enrolled, retired)`` handles for
    logging. Hand-mapped (non-``managed``) bindings are never retired here.
    """
    agents = [
        a
        for a in bridge.list_agents()
        if a.get("workspace_id") == workspace
        and a.get("pane_id")
        and (kind is None or a.get("agent") == kind)
    ]
    live_panes = {str(a["pane_id"]) for a in agents}
    # Each looked up once, and only if this pass finds an agent no mapping has.
    tab_labels = functools.cache(lambda: bridge.tab_labels(workspace))
    owner = functools.cache(lambda: _owner(config))
    # Seed with the room's existing handles so a new pane never collides with one.
    taken = {m.handle for m in bridge.registry.all() if m.room == room}

    enrolled = [
        h
        for a in agents
        if (
            h := _enroll_one(
                config,
                bridge,
                room,
                a,
                taken=taken,
                name_from=name_from,
                prefix=prefix,
                tab_labels=tab_labels,
                owner=owner,
            )
        )
        is not None
    ]
    # Retire on the pane closing, not on its agent stopping. After herdr's server
    # restarts, every pane comes back at a bare shell: those agents stopped, they
    # didn't leave, and retiring them would delete them from the room.
    # A pane is closed only when no workspace has it open: a room can be bound
    # to several workspaces, and each one's pass sees the others' members in the
    # registry. Counting only this workspace's panes, two bindings retired and
    # re-enrolled each other's members on every pass.
    try:
        open_panes = {str(p["pane_id"]) for p in bridge.list_panes() if p.get("pane_id")}
    except HerdrError:
        return enrolled, []  # can't tell which panes are open: retire nothing
    retired: list[str] = []
    for m in bridge.registry.all():
        if m.room == room and m.managed and m.pane not in live_panes | open_panes:
            _retire_one(config, bridge, m)
            retired.append(m.handle)
    return enrolled, retired


@doc_ref(
    usage="mycelium herdr status",
    desc="Show whether herdr is installed and reachable.",
    group="agent",
)
@app.command("status")
@emits_json()
def herdr_status(ctx: typer.Context) -> None:
    """Report herdr availability, the precondition for the wake path."""
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    def report(installed: bool, reachable: bool, agents: int = 0, bindings: int = 0) -> None:
        state = {
            "installed": installed,
            "reachable": reachable,
            "live_agents": agents,
            "bindings": bindings,
        }
        typer.echo(json.dumps(state, indent=2))

    try:
        bridge = _bridge()
        if not bridge.binary_present():
            if as_json:
                report(installed=False, reachable=False)
                raise typer.Exit(1)
            console.print("[yellow]herdr not installed[/yellow]; the wake layer is unavailable.")
            console.print(
                "[dim]Install from https://herdr.dev; mycelium works fine without it.[/dim]"
            )
            raise typer.Exit(1)
        if not bridge.available():
            if as_json:
                report(installed=True, reachable=False)
                raise typer.Exit(1)
            console.print("[yellow]herdr installed but server unreachable.[/yellow]")
            raise typer.Exit(1)
        agents = bridge.list_agents()
        if as_json:
            report(True, True, len(agents), len(bridge.registry.all()))
            return
        console.print(
            f"[green]herdr reachable[/green]: {len(agents)} live agent(s), "
            f"{len(bridge.registry.all())} mycelium binding(s)."
        )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr wake <handle> [--room <room>] [--timeout-ms N]",
    desc="Wake a mapped agent to run one mycelium coordination turn.",
    group="agent",
)
@app.command("wake")
@in_room("room")
def herdr_wake(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle to wake."),
    room: str | None = None,
    timeout_ms: int = typer.Option(120000, "--timeout-ms", help="Wake wait budget (ms)."),
) -> None:
    """Prompt the mapped herdr pane to drain its pending mycelium turn.

    The agent wakes *in place* with full context and replies through the room.
    Fail-soft: an unreachable herdr, missing mapping, stale pane, or busy agent
    all report cleanly and exit non-zero (the message stays on the cursor).
    """
    try:
        room_name = str(room)
        bridge = _bridge()

        if not bridge.available():
            console.print(
                "[yellow]herdr not reachable[/yellow]; cannot wake; message stays on the cursor."
            )
            raise typer.Exit(1)

        mapping = bridge.registry.get(room_name, handle)
        if mapping is None:
            console.print(
                f"[yellow]No herdr pane mapped[/yellow] for @{handle.lstrip('@')} in {room_name}.\n"
                f"[dim]Bind one: mycelium herdr map {handle.lstrip('@')} <pane> --room {room_name}[/dim]"
            )
            raise typer.Exit(1)

        console.print(f"[dim]Waking @{mapping.handle} at {mapping.pane}…[/dim]")
        result = bridge.wake(
            mapping, build_wake_prompt(room_name, mapping.handle), timeout_ms=timeout_ms
        )
        if result.ok:
            console.print(f"[green]Woke[/green] @{mapping.handle} [dim]{result.detail}[/dim]")
        else:
            console.print(f"[yellow]Not woken[/yellow] [dim]{result.detail}[/dim]")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except HerdrError as e:
        console.print(f"[red]herdr error:[/red] {e}")
        raise typer.Exit(1) from None


#: What herdr reports of an agent taking a turn. A session seen like this has a
#: conversation in it; one only ever seen idle or blocked may be a fresh one,
#: stopped at its first-run question.
_WORKED_STATES = frozenset({"working"})


def _collect_presence(
    bridge: HerdrBridge, room_filter: str | None
) -> dict[str, dict[str, dict[str, str | None]]]:
    """Current herdr liveness for every mapped handle →
    ``{room: {handle: {"status": ..., "title": ...}}}``.

    ``title`` is herdr's terminal title (the agent's current task), so the roster
    can show *what* each agent is doing, not just that it's alive. Only mapped
    handles whose pane currently hosts a live agent are included; an unmapped/dead
    pane is omitted so its backend entry lapses on its TTL.
    """
    agents = [a for a in bridge.list_agents() if a.get("pane_id")]
    live: dict[str, dict[str, str | None]] = {
        str(a["pane_id"]): {
            "status": str(a.get("agent_status") or "unknown"),
            "title": (a.get("terminal_title_stripped") or a.get("terminal_title") or None),
        }
        for a in agents
    }
    # Each mapped pane's session, kept while herdr can still say it, so a
    # restart or a rename resumes the agent's conversation once it can't. The
    # one kept is the one its agent last worked in: a pane herdr brought back
    # as a fresh, idle session doesn't replace it.
    sessions = {
        str(a["pane_id"]): (s, a.get("agent_status")) for a in agents if (s := session_of(a))
    }
    bridge.registry.note_sessions(
        {pane: s for pane, (s, status) in sessions.items() if status in _WORKED_STATES},
        {pane: s for pane, (s, _status) in sessions.items()},
    )
    view: dict[str, dict[str, dict[str, str | None]]] = {}
    for m in bridge.registry.all():
        if room_filter and m.room != room_filter:
            continue
        state = live.get(m.pane)
        if state is not None:
            view.setdefault(m.room, {})[m.handle] = state
    return view


@functools.cache
def sync_source() -> str | None:
    """This machine, as the hub tells its pushes apart: its runner id.

    Several machines' agents can share a room, each machine's sync pushing
    only its own agents, so the hub keeps each machine's push apart rather
    than letting one replace another's, and hands a machine only the wakes
    for agents it reported. ``None`` when the id can't be read or made.
    """
    try:
        from mycelium.runner.daemon import runner_id

        return runner_id()
    except Exception as e:  # noqa: BLE001 - without it, the hub treats the push as before
        _sync.warning("no runner id for this machine: %s", e)
        return None


def _hub_call(
    config: MyceliumConfig,
    http: httpx.Client | None,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> httpx.Response:
    """One hub call: on the pass's own client when there is one (its connection
    kept, its credential got once), else on its own."""
    import httpx

    from mycelium.client import auth_headers

    if http is not None:
        return http.request(method, path, json=json, params=params)
    url = f"{config.server.api_url}{path}"
    headers = auth_headers(config)
    if method == "POST":
        return httpx.post(url, json=json, params=params, timeout=5.0, headers=headers)
    return httpx.get(url, params=params, timeout=5.0, headers=headers)


def _push_presence(
    config: MyceliumConfig,
    room: str,
    statuses: dict[str, dict[str, str | None]],
    ttl_s: float,
    *,
    http: httpx.Client | None = None,
) -> bool:
    """POST one room's herdr liveness to the backend. Best-effort → ``bool`` ok."""
    what = f"hub presence for {room}"
    started = time.monotonic()
    body: dict = {"statuses": statuses, "ttl_s": ttl_s}
    if (source := sync_source()) is not None:
        body["source"] = source
    try:
        path = f"/api/rooms/{room}/sessions/herdr-presence"
        resp = _hub_call(config, http, "POST", path, json=body)
        if _not_on_hub(room, resp):
            return False
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 - presence is best-effort; the next pass renews it
        failing(_hub, what, f"{what} failed after {ms(started)}ms: {e}")
        return False
    recovered(_hub, what)
    slow(_hub, what, started)
    return True


def wake_prompt_for(room: str, wake: dict) -> str:
    """The prompt a queued wake turns into.

    The hub's digest when it sent one. Otherwise worded by why it was queued:
    a ``turn`` or a mention is read through ``await``, so the reply lands
    where it was asked and the room sees the agent responding; an
    ``assigned`` row names the row to take.
    """
    # The hub builds the digest the agent is told (why it woke, what changed,
    # the messages that asked for it); a hub from before that sends none.
    if isinstance(wake.get("prompt"), str) and wake["prompt"].strip():
        return wake["prompt"]
    handle = str(wake.get("handle") or "")
    reason = wake.get("reason")
    if reason == "turn":
        return build_wake_prompt(room, handle)
    if reason == "assigned" and wake.get("key"):
        return build_assigned_prompt(room, handle, str(wake["key"]), wake.get("title"))
    return build_mention_prompt(room, handle)


def fetch_wakes(
    config: MyceliumConfig, room: str, *, http: httpx.Client | None = None
) -> list[dict]:
    """Take a room's queued wakes off the backend; ``[]`` when it can't be reached.

    Taking them drains the queue, so whoever fetches delivers. This machine
    asks only for the wakes of the agents its own push reported
    (:func:`sync_source`), so another machine's wakes wait for that machine.
    """
    what = f"hub wakes for {room}"
    started = time.monotonic()
    source = sync_source()
    try:
        path = f"/api/rooms/{room}/sessions/herdr-wakes"
        params = {"source": source} if source is not None else None
        resp = _hub_call(config, http, "GET", path, params=params)
        if _not_on_hub(room, resp):
            return []
        resp.raise_for_status()
        wakes = resp.json().get("wakes", [])
    except Exception as e:  # noqa: BLE001 - the queue keeps them for the next pass
        failing(_hub, what, f"{what} failed after {ms(started)}ms: {e}")
        return []
    recovered(_hub, what)
    slow(_hub, what, started)
    return [w for w in wakes if isinstance(w, dict)]


def outcome(wake: dict, *, delivered: bool, why: str | None = None) -> dict | None:
    """What became of ``wake``, for :func:`report_wakes`; None for one with no id
    (from a hub that keeps no wake log)."""
    if not wake.get("id"):
        return None
    said: dict = {"id": str(wake["id"]), "delivered": delivered}
    if why:
        said["why"] = why[:300]
    return said


def report_wakes(
    config: MyceliumConfig,
    room: str,
    outcomes: list[dict | None],
    *,
    http: httpx.Client | None = None,
) -> None:
    """Tell the hub what became of the wakes this pass drained, for its wake log.

    Best-effort: a hub that can't be reached, or is from before the log, just
    records them as handed without a word from here.
    """
    said = [o for o in outcomes if o]
    if not said:
        return
    try:
        path = f"/api/rooms/{room}/sessions/herdr-wakes/outcomes"
        _hub_call(config, http, "POST", path, json={"outcomes": said})
    except Exception as e:  # noqa: BLE001 - the log says "handed" without it
        _sync.info("couldn't report %d wake outcome(s) in %s: %s", len(said), room, e)


def _drain_wakes(
    config: MyceliumConfig,
    bridge: HerdrBridge,
    room: str,
    *,
    log: Console | None = None,
    wait: bool = True,
    http: httpx.Client | None = None,
) -> int:
    """Drain the backend's herdr wake queue for a room and run each wake.

    The "commands down" leg: the backend queued a wake when a tag mentioned a
    herdr-present-but-not-joined handle, a turn was put to one, or a row was
    filed for one; here — the only place that can reach the herdr socket — we
    turn each into a ``herdr agent prompt``. ``wait=False`` hands each prompt
    over without waiting for the turn to settle, so the agents woken in one
    pass work at the same time. Returns the number of agents actually woken.
    """
    out = log if log is not None else console
    woke = 0
    outcomes: list[dict | None] = []
    for w in fetch_wakes(config, room, http=http):
        handle = str(w.get("handle") or "")
        reason = w.get("reason") or "mention"
        mapping = bridge.registry.get(room, handle)
        if mapping is None:
            _sync.warning("wake @%s (%s) in %s: no pane here is bound to it", handle, reason, room)
            outcomes.append(outcome(w, delivered=False, why="no herdr pane here is bound to it"))
            continue
        prompt = wake_prompt_for(room, w)
        line = f"wake @{handle} ({reason}) -> {mapping.pane}"
        started = time.monotonic()
        try:
            result = bridge.wake(
                mapping, prompt, timeout_ms=config.herdr.wake_timeout_ms, wait=wait
            )
        except HerdrError as e:
            _sync.warning("%s failed %dms: %s", line, ms(started), e)
            outcomes.append(outcome(w, delivered=False, why=f"herdr refused it: {e}"))
            continue
        if result.ok:
            woke += 1
            _sync.info("%s ok %dms", line, ms(started))
            out.print(f"[green]↯ woke[/green] @{handle} [dim]on {reason} → {mapping.pane}[/dim]")
            outcomes.append(outcome(w, delivered=True))
        else:
            _sync.info("%s skipped %dms: %s", line, ms(started), result.detail)
            out.print(f"[yellow]↯ skip[/yellow] @{handle} [dim]{result.detail}[/dim]")
            outcomes.append(outcome(w, delivered=False, why=result.detail))
    report_wakes(config, room, outcomes, http=http)
    return woke


def _reason(err: Exception) -> str:
    """One line saying why a binding failed: the hub's own message when it answered."""
    from mycelium.client import hub_error_detail
    from mycelium_backend_client.errors import UnexpectedStatus

    if isinstance(err, UnexpectedStatus):
        return f"the hub answered {err.status_code}: {hub_error_detail(err.content)}"
    return " ".join(str(err).split()) or type(err).__name__


class SyncResult(NamedTuple):
    """What one :func:`sync_pass` did, and the bindings it couldn't reconcile."""

    enrolled: int
    retired: int
    states: int
    #: ``{workspace: (room, error)}`` for each binding whose reconcile raised.
    failed: dict[str, tuple[str, str]]


class BindingSyncError(Exception):
    """Some bound workspaces couldn't be reconciled; the rest of the pass still ran.

    Raised by the runner's herdr host after the pass, so the runner reports
    which bindings fail (``Runner.sync_health``) and ``mycelium machine`` can
    name them.
    """

    def __init__(self, failed: dict[str, tuple[str, str]]) -> None:
        self.failed = failed
        super().__init__("; ".join(f"{ws} → {r}: {err}" for ws, (r, err) in failed.items()))


def sync_pass(
    config: MyceliumConfig,
    bridge: HerdrBridge,
    targets: list[tuple[str, str]],
    *,
    room_filter: str | None,
    ttl_s: float,
    name_from: str = "tab",
    prefix: str = "",
    kind: str | None = None,
    log: Console | None = None,
    wait: bool = True,
) -> SyncResult:
    """One reconcile of the bound workspaces: membership, liveness up, wakes down.

    A binding that fails to reconcile is logged and reported in ``failed``; the
    other bindings, presence and wakes still go ahead, so one bad binding can't
    leave every agent on the machine unwoken. Shared by ``herdr sync`` and
    ``swarm``, which runs it on a background thread while it shows the room and
    does not wait on a woken agent (``wait``), since its members work at once.
    """
    out = log if log is not None else console
    enrolled = retired = 0
    failed: dict[str, tuple[str, str]] = {}
    for ws, r in targets:
        if _left_out(r):
            continue
        what = f"binding {ws} -> {r}"
        try:
            e, x = _reconcile_workspace(
                config, bridge, ws, r, name_from=name_from, prefix=prefix, kind=kind
            )
        except Exception as err:  # noqa: BLE001 - one binding must not stop the others
            failed[ws] = (r, _reason(err))
            failing(_sync, what, f"{what} failed: {err!r}")
            out.print(f"[red]✗ {escape(ws)} → {escape(r)}[/red] [dim]{escape(failed[ws][1])}[/dim]")
            continue
        recovered(_sync, what)
        for h in e:
            _sync.info("enrolled @%s (%s -> %s)", h, ws, r)
            out.print(f"[green]＋ enrolled[/green] @{h} [dim]({ws} → {r})[/dim]")
        for h in x:
            _sync.info("retired @%s (pane closed in %s)", h, r)
            out.print(f"[yellow]－ retired[/yellow] @{h} [dim](pane closed in {r})[/dim]")
        enrolled += len(e)
        retired += len(x)
    view = _collect_presence(bridge, room_filter)
    rooms = sorted(r for r in {r for _, r in targets} | set(view) if not _left_out(r))
    _sync_rooms(config, bridge, rooms, view, ttl_s=ttl_s, log=out, wait=wait)
    return SyncResult(enrolled, retired, sum(len(v) for v in view.values()), failed)


def _sync_rooms(
    config: MyceliumConfig,
    bridge: HerdrBridge,
    rooms: list[str],
    view: dict[str, dict[str, dict[str, str | None]]],
    *,
    ttl_s: float,
    log: Console,
    wait: bool,
) -> None:
    """Each room's presence up, then its wakes down, every room at once.

    On the one client the passes share (:func:`_pass_client`), so the hub's
    connections stay open from one pass to the next instead of a new one, and
    a TLS handshake, per call. A hub slow to answer one room holds up that
    room only, for a few seconds.
    """
    import httpx

    if not rooms:
        return
    try:
        http = _pass_client(config)
    except httpx.HTTPError as e:
        # The credential couldn't be got: no room can be asked this pass.
        failing(_hub, "hub client", f"no hub calls this pass: {e}")
        return
    recovered(_hub, "hub client")

    def one(room: str) -> None:
        if (statuses := view.get(room)) is not None:
            _push_presence(config, room, statuses, ttl_s, http=http)
        if not _left_out(room):
            _drain_wakes(config, bridge, room, log=log, wait=wait, http=http)

    with ThreadPoolExecutor(max_workers=min(8, len(rooms))) as pool:
        list(pool.map(one, rooms))


#: ``{hub url: client}`` the sync passes share, kept open between passes.
_pass_clients: dict[str, httpx.Client] = {}


def _pass_client(config: MyceliumConfig) -> httpx.Client:
    """The client the sync passes share for ``config``'s hub, its credential got
    now: once a pass, before any room is asked, never inside a call."""
    from mycelium.client import auth_headers, hub_client, issued_by

    url = config.server.api_url
    http = _pass_clients.get(url)
    if http is None or http.is_closed:
        http = _pass_clients[url] = hub_client(config, timeout=PASS_TIMEOUT_S)
        return http
    credentials = auth_headers(config) if issued_by(config, url) else {}
    http.headers.pop("Authorization", None)
    http.headers.update(credentials)
    return http


#: How long one pass's liveness stands on the hub; the runner's next pass renews it.
SYNC_TTL_S = 90.0


@doc_ref(
    usage="mycelium herdr sync [--workspace <id> --room <room>]",
    desc="Bind a herdr workspace to a room and sync it once; the runner keeps it synced.",
    group="agent",
)
@app.command("sync")
@in_room("room", resolve=False)  # no room: every bound workspace
def herdr_sync(
    ctx: typer.Context,
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="herdr workspace id to bind to --room (e.g. w2)."
    ),
    room: str | None = None,
    name_from: str = typer.Option(
        "tab", "--name-from", help="Handle source for new agents: 'tab' or 'pane'."
    ),
    prefix: str = typer.Option(
        "", "--prefix", help="Handle prefix for new agents (e.g. 'agent-')."
    ),
    kind: str | None = typer.Option(None, "--kind", help="Only enroll agents of this herdr kind."),
) -> None:
    """Make a herdr workspace *be* a mycelium room, and sync it once.

    Pass ``--workspace w2 --room myroom`` to **bind** them. A pass then:

    - **membership** — enrolls every live agent in the workspace as a room
      member (manifest + handle↔pane, handle from the tab name); a member whose
      pane closes leaves the room.
    - **liveness** — pushes each member's herdr state (idle/working/blocked) to
      the hub, which can't see herdr on this machine.
    - **wakes** — delivers queued ``@``-mention doorbells to the right pane.

    Keeping that going is the runner's job (``mycelium runner``): it syncs every
    bound workspace on this machine, so binding one is all it takes. This runs
    one pass now, so the workspace's agents join at once, and says whether the
    runner is up. It only *drives* agents you started in herdr; it never
    spawns panes.
    """
    from mycelium.commands.runner import running_pid

    try:
        config = MyceliumConfig.load()
        bridge = _bridge()
        if not bridge.available():
            console.print("[yellow]herdr not reachable[/yellow]; nothing to sync.")
            raise typer.Exit(1)

        room_name = room or None
        if workspace and room_name:
            bridge.registry.bind(workspace, room_name)
            console.print(
                f"[green]Bound[/green] workspace [cyan]{workspace}[/cyan] → "
                f"room [cyan]{room_name}[/cyan]."
            )
        elif workspace or room_name:
            console.print(
                "[yellow]Binding needs both[/yellow] --workspace and --room; "
                "reconciling existing bindings only."
            )

        # The (workspace, room) pairs this run reconciles: persisted bindings,
        # filtered by any --workspace/--room the caller scoped to.
        targets = [
            (ws, r)
            for ws, r in bridge.registry.bindings().items()
            if (workspace is None or ws == workspace) and (room_name is None or r == room_name)
        ]
        if not targets:
            console.print(
                "[dim]No workspace bindings. Bind one:[/dim] "
                "[cyan]mycelium herdr sync --workspace <id> --room <room>[/cyan]"
            )
            raise typer.Exit(1)

        enrolled, retired, states, failed = sync_pass(
            config,
            bridge,
            targets,
            room_filter=room_name,
            ttl_s=SYNC_TTL_S,
            name_from=name_from,
            prefix=prefix,
            kind=kind,
        )
        console.print(
            f"[green]Synced[/green] {states} live state(s) across {len(targets)} binding(s) "
            f"[dim](+{enrolled} enrolled, -{retired} retired)[/dim]"
        )
        if failed:
            console.print(
                f"[red]{len(failed)} binding(s) failed to sync[/red] (listed above). "
                "Unbind one with [cyan]mycelium herdr unbind <workspace>[/cyan]."
            )
        if running_pid():
            console.print("[dim]This machine's runner keeps them synced from here.[/dim]")
        else:
            console.print(
                "[yellow]Nothing keeps them synced:[/yellow] agents here won't hear their "
                "mentions until the runner is running. Start it with "
                "[cyan]mycelium runner --detach[/cyan]."
            )
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr unbind <workspace>",
    desc="Stop syncing a herdr workspace with its room; its agents stay in the room.",
    group="agent",
)
@app.command("unbind")
def herdr_unbind(
    ctx: typer.Context,
    workspace: str = typer.Argument(..., help="herdr workspace id to unbind (e.g. w2)."),
) -> None:
    """Forget a ``workspace -> room`` binding, so the runner stops syncing it.

    Its members stay in the room and their handle↔pane mappings stay; nothing
    enrolls or retires them until the workspace is bound again.
    """
    try:
        bridge = _bridge()
        room = bridge.registry.bindings().get(workspace)
        if room is None:
            console.print(f"[yellow]No binding[/yellow] for workspace {escape(workspace)}")
            raise typer.Exit(1)
        bridge.registry.unbind(workspace)
        console.print(f"[green]Unbound[/green] {escape(workspace)} [dim]from {escape(room)}[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None
