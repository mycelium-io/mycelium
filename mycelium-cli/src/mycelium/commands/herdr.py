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

import re

import typer
from rich.console import Console
from rich.table import Table

from mycelium.commands.room import _resolve_room
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.integrations.herdr import (
    HerdrBridge,
    HerdrError,
    HerdrPaneMapping,
    build_mention_prompt,
    build_wake_prompt,
)

app = typer.Typer(
    help="Bind mycelium handles to persistent herdr agent panes (optional wake layer).",
    no_args_is_help=True,
)
console = Console()


def _bridge() -> HerdrBridge:
    return HerdrBridge()


@doc_ref(
    usage="mycelium herdr map <handle> <pane> [--room <room>] [--kind <kind>]",
    desc="Bind a mycelium handle to a herdr agent pane (e.g. w2:pV).",
    group="agent",
)
@app.command("map")
def herdr_map(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle (without leading @)."),
    pane: str = typer.Argument(..., help="herdr pane id hosting the agent, e.g. w2:pV."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
    kind: str | None = typer.Option(None, "--kind", help="herdr agent kind (claude, pi, …)."),
) -> None:
    """Record a durable ``handle -> pane`` binding used by wake.

    Validates the pane against herdr's live agent list when herdr is reachable
    (a warning, not a hard failure — you can map ahead of starting the agent).
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
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
def herdr_unmap(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
) -> None:
    """Forget a ``handle -> pane`` binding."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
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
    usage="mycelium herdr unbind <workspace>",
    desc="Remove a workspace → room binding so sync stops reconciling it.",
    group="agent",
)
@app.command("unbind")
def herdr_unbind(
    ctx: typer.Context,
    workspace: str = typer.Argument(..., help="herdr workspace, by label or id."),
) -> None:
    """Forget a ``workspace -> room`` binding.

    The counterpart to ``sync --workspace … --room …``. Binding a workspace
    enrolls every live agent in it, so the way back out has to be a command
    rather than a hand-edit of the registry file.
    """
    try:
        bridge = _bridge()
        bindings = bridge.registry.bindings()
        target = workspace
        if target not in bindings:
            # Accept the label here too, but never require herdr to be up to
            # undo something: a closed workspace can still be unbound by id.
            try:
                target = bridge.resolve_workspace(workspace)
            except HerdrError:
                target = workspace
        room_name = bindings.get(target)
        if bridge.registry.unbind(target):
            shown = f"{workspace} ({target})" if workspace != target else target
            console.print(
                f"[green]Unbound[/green] workspace [cyan]{shown}[/cyan]"
                f"{f' [dim]from {room_name}[/dim]' if room_name else ''}."
            )
            console.print(
                "[dim]Members it enrolled stay in the room; remove them with[/dim] "
                "[cyan]mycelium agent rm <handle> --room <room>[/cyan]"
            )
        else:
            console.print(f"[yellow]No binding[/yellow] for workspace {workspace!r}")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


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
def herdr_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Only this room."),
) -> None:
    """Reconcile each binding across three views: the registry, the backend's
    presence (``slim``/``lease``), and herdr's live agent list.

    The backend runs containerized and is herdr-blind, so its presence lease can
    outlive an agent that has stopped looping ``await``. This is the one place
    that can cross-check — so a lease with a dead pane shows as **stale lease**,
    and a live herdr agent the backend never joined shows as **herdr-only**.
    """
    try:
        config = MyceliumConfig.load()
        bridge = _bridge()
        mappings = bridge.registry.all()
        if room:
            room_name = _resolve_room(config, room)
            mappings = [m for m in mappings if m.room == room_name]

        if not mappings:
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
        base = _sanitize_handle(tab_label, prefix)
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
    tab_labels: dict[str, str],
    sender: str,
) -> str | None:
    """Ensure one live herdr agent is a member of ``room``; return its handle if
    this call newly enrolled it (``None`` if it was already bound).

    Idempotency is keyed on the **pane**, not the derived handle: if any mapping
    in the room already points at this pane, the agent is already a member (we
    just re-materialize its manifest if it went missing). Only a genuinely new
    pane derives a fresh handle — collision-checked against the room's existing
    handles — and gets a manifest + a ``managed`` mapping.
    """
    from mycelium.commands.agent import _load_manifest, _write_manifest
    from mycelium.integrations import AddOptions, get_integration

    pane = str(agent["pane_id"])
    existing = next((m for m in bridge.registry.all() if m.room == room and m.pane == pane), None)
    if existing is not None:
        # Already bound to this pane — heal a manifest that was deleted out from
        # under us so the member doesn't silently drop off the roster.
        if _load_manifest(room, existing.handle) is None:
            impl = get_integration("claude_code", cwd=agent.get("cwd"))
            manifest = impl.build_manifest(
                handle=existing.handle,
                opts=AddOptions(room=room),
                description=f"herdr-enrolled from {pane} ({agent.get('agent')})",
                allow_from=[],
                owner=sender,
            )
            _write_manifest(config, room, manifest, created_by=sender)
        return None

    handle = _derive_handle(
        tab_label=tab_labels.get(str(agent.get("tab_id") or ""), ""),
        pane_id=pane,
        prefix=prefix,
        name_from=name_from,
        taken=taken,
    )
    taken.add(handle)
    impl = get_integration("claude_code", cwd=agent.get("cwd"))
    manifest = impl.build_manifest(
        handle=handle,
        opts=AddOptions(room=room),
        description=f"herdr-enrolled from {pane} ({agent.get('agent')})",
        allow_from=[],
        owner=sender,
    )
    _write_manifest(config, room, manifest, created_by=sender)
    bridge.registry.set(
        HerdrPaneMapping(room=room, handle=handle, pane=pane, kind=agent.get("agent"), managed=True)
    )
    return handle


def _retire_one(config: MyceliumConfig, bridge: HerdrBridge, mapping: HerdrPaneMapping) -> None:
    """Remove a sync-managed member whose herdr pane is gone: deregister its
    manifest (notes/logs preserved) and drop the mapping. The teardown half of
    "herdr lifecycle *is* mycelium lifecycle."""
    from mycelium.commands.agent import _delete_manifest, _load_manifest

    manifest = _load_manifest(mapping.room, mapping.handle)
    if manifest is not None:
        _delete_manifest(config, mapping.room, manifest)
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
    member whose pane has closed. Returns ``(enrolled, retired)`` handles for
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
    tab_labels = bridge.tab_labels(workspace) if name_from == "tab" else {}
    sender = config.get_current_identity()
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
                sender=sender,
            )
        )
        is not None
    ]
    retired: list[str] = []
    for m in bridge.registry.all():
        if m.room == room and m.managed and m.pane not in live_panes:
            _retire_one(config, bridge, m)
            retired.append(m.handle)
    return enrolled, retired


@doc_ref(
    usage="mycelium herdr status",
    desc="Show whether herdr is installed and reachable.",
    group="agent",
)
@app.command("status")
def herdr_status(ctx: typer.Context) -> None:
    """Report herdr availability, the precondition for the wake path."""
    try:
        bridge = _bridge()
        if not bridge.binary_present():
            console.print("[yellow]herdr not installed[/yellow]; the wake layer is unavailable.")
            console.print(
                "[dim]Install from https://herdr.dev; mycelium works fine without it.[/dim]"
            )
            raise typer.Exit(1)
        if not bridge.available():
            console.print("[yellow]herdr installed but server unreachable.[/yellow]")
            raise typer.Exit(1)
        agents = bridge.list_agents()
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
def herdr_wake(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Mycelium agent handle to wake."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
    timeout_ms: int = typer.Option(120000, "--timeout-ms", help="Wake wait budget (ms)."),
) -> None:
    """Prompt the mapped herdr pane to drain its pending mycelium turn.

    The agent wakes *in place* with full context and replies through the room.
    Fail-soft: an unreachable herdr, missing mapping, stale pane, or busy agent
    all report cleanly and exit non-zero (the message stays on the cursor).
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
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
    live: dict[str, dict[str, str | None]] = {
        str(a["pane_id"]): {
            "status": str(a.get("agent_status") or "unknown"),
            "title": (a.get("terminal_title_stripped") or a.get("terminal_title") or None),
        }
        for a in bridge.list_agents()
        if a.get("pane_id")
    }
    view: dict[str, dict[str, dict[str, str | None]]] = {}
    for m in bridge.registry.all():
        if room_filter and m.room != room_filter:
            continue
        state = live.get(m.pane)
        if state is not None:
            view.setdefault(m.room, {})[m.handle] = state
    return view


def _push_presence(
    config: MyceliumConfig, room: str, statuses: dict[str, dict[str, str | None]], ttl_s: float
) -> bool:
    """POST one room's herdr liveness to the backend. Best-effort → ``bool`` ok."""
    import httpx

    from mycelium.client import auth_headers

    try:
        url = f"{config.server.api_url}/api/rooms/{room}/sessions/herdr-presence"
        resp = httpx.post(
            url,
            json={"statuses": statuses, "ttl_s": ttl_s},
            timeout=5.0,
            headers=auth_headers(config),
        )
        resp.raise_for_status()
    except Exception:
        return False
    return True


def _drain_wakes(config: MyceliumConfig, bridge: HerdrBridge, room: str) -> int:
    """Drain the backend's herdr wake queue for a room and run each wake.

    The "commands down" leg: the backend queued a wake when a tag mentioned a
    herdr-present-but-not-joined handle; here — the only place that can reach the
    herdr socket — we turn each into a ``herdr agent prompt``. The mention text
    rides inline (no await), so the woken agent replies straight to the room.
    Returns the number of agents actually woken.
    """
    import httpx

    from mycelium.client import auth_headers

    try:
        url = f"{config.server.api_url}/api/rooms/{room}/sessions/herdr-wakes"
        resp = httpx.get(url, timeout=5.0, headers=auth_headers(config))
        resp.raise_for_status()
        wakes = resp.json().get("wakes", [])
    except Exception:
        return 0

    woke = 0
    for w in wakes:
        handle = str(w.get("handle") or "")
        mapping = bridge.registry.get(room, handle)
        if mapping is None:
            continue
        prompt = build_mention_prompt(room, handle)
        try:
            result = bridge.wake(mapping, prompt, timeout_ms=config.herdr.wake_timeout_ms)
        except HerdrError:
            continue
        if result.ok:
            woke += 1
            console.print(f"[green]↯ woke[/green] @{handle} [dim]on mention → {mapping.pane}[/dim]")
        else:
            console.print(f"[yellow]↯ skip[/yellow] @{handle} [dim]{result.detail}[/dim]")
    return woke


@doc_ref(
    usage="mycelium herdr sync [--workspace <label> --room <room>] [--once] [--interval N]",
    desc="Bind a herdr workspace to a room and reconcile membership, liveness, and wakes.",
    group="agent",
)
@app.command("sync")
def herdr_sync(
    ctx: typer.Context,
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="herdr workspace to bind to --room, by label or id (e.g. 'Mycelium' or w2).",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to bind/reconcile (scopes to bound workspaces)."
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help="Reconcile a single pass and exit (default keeps watching on an interval).",
    ),
    interval: int = typer.Option(5, "--interval", help="Poll interval seconds while watching."),
    name_from: str = typer.Option(
        "tab", "--name-from", help="Handle source for new agents: 'tab' or 'pane'."
    ),
    prefix: str = typer.Option(
        "", "--prefix", help="Handle prefix for new agents (e.g. 'agent-')."
    ),
    kind: str | None = typer.Option(None, "--kind", help="Only enroll agents of this herdr kind."),
) -> None:
    """The one bridge that makes a herdr workspace *be* a mycelium room.

    Pass ``--workspace w2 --room myroom`` once to **bind** them; from then on this
    watches that binding, reconciling every ``interval`` (pass ``--once`` for a
    single pass and exit):

    - **membership** — every live agent in the workspace is enrolled as a room
      member (manifest + handle↔pane, handle from the tab name); a member whose
      pane closes leaves the room. The roster tracks the workspace with no manual
      ``map``/``enroll`` step.
    - **liveness** — each member's herdr state (idle/working/blocked) is pushed to
      the backend so the UI badges it (the backend is containerized and can't see
      the herdr socket; this host-side loop is the only thing that can).
    - **wakes** — queued ``@``-mention doorbells are drained and delivered to the
      right pane.

    Bindings persist, so a bare ``mycelium herdr sync`` watches every bound
    workspace. Watching is the default because the wake leg is a host-side loop:
    the backend is containerized and can't reach the herdr socket, so nothing
    delivers a queued ``@``-mention to its pane unless this keeps draining. This
    only *drives* agents you started in herdr; it never spawns panes. Ctrl-C
    clears the liveness overlay.
    """
    import time

    try:
        config = MyceliumConfig.load()
        bridge = _bridge()
        if not bridge.available():
            console.print("[yellow]herdr not reachable[/yellow]; nothing to sync.")
            raise typer.Exit(1)

        room_name = _resolve_room(config, room) if room else None
        selector = workspace
        if workspace:
            try:
                workspace = bridge.resolve_workspace(workspace)
            except HerdrError:
                # A workspace that has since closed can still be named to scope
                # a reconcile, so accept the literal when it is already bound.
                if workspace not in bridge.registry.bindings():
                    raise
        if workspace and room_name:
            bridge.registry.bind(workspace, room_name)
            shown = f"{selector} ({workspace})" if selector != workspace else workspace
            console.print(
                f"[green]Bound[/green] workspace [cyan]{shown}[/cyan] → "
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
                "[cyan]mycelium herdr sync --workspace <label> --room <room>[/cyan]"
            )
            raise typer.Exit(1)

        ttl_s = max(90.0, interval * 4.0)

        def reconcile_and_push() -> tuple[int, int, int]:
            """One pass: reconcile every target, then push liveness + drain wakes
            for the touched rooms. Returns (enrolled, retired, states-pushed)."""
            enrolled = retired = 0
            for ws, r in targets:
                e, x = _reconcile_workspace(
                    config, bridge, ws, r, name_from=name_from, prefix=prefix, kind=kind
                )
                for h in e:
                    console.print(f"[green]＋ enrolled[/green] @{h} [dim]({ws} → {r})[/dim]")
                for h in x:
                    console.print(
                        f"[yellow]－ retired[/yellow] @{h} [dim](pane closed in {r})[/dim]"
                    )
                enrolled += len(e)
                retired += len(x)
            view = _collect_presence(bridge, room_name)
            for r, statuses in view.items():
                _push_presence(config, r, statuses, ttl_s)
            for r in {r for _, r in targets} | set(view):
                _drain_wakes(config, bridge, r)
            return enrolled, retired, sum(len(v) for v in view.values())

        enrolled, retired, states = reconcile_and_push()
        console.print(
            f"[green]Synced[/green] {states} live state(s) across {len(targets)} binding(s) "
            f"[dim](+{enrolled} enrolled, -{retired} retired)[/dim]"
            + (" [dim](one-shot)[/dim]" if once else "")
        )
        if once:
            return

        console.print(
            f"[dim]Watching herdr every {interval}s "
            f"(membership + presence up, wakes down). Ctrl-C to stop.[/dim]"
        )
        rooms_touched = {r for _, r in targets}
        try:
            while True:
                time.sleep(interval)
                reconcile_and_push()
        except KeyboardInterrupt:
            for r in rooms_touched:
                _push_presence(config, r, {}, ttl_s)
            console.print("\n[dim]Stopped; cleared herdr overlay.[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None
