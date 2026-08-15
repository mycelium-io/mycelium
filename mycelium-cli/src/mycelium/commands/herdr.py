# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium herdr`` — bind mycelium handles to persistent herdr agent panes.

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
                    f"[yellow]Note:[/yellow] no live agent at pane [cyan]{pane}[/cyan] yet — "
                    "mapping saved; wake will re-check at call time."
                )
            else:
                resolved_kind = resolved_kind or agent.get("agent")
        else:
            console.print("[dim]herdr not reachable — saving mapping without validation.[/dim]")

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


def _room_members(config: MyceliumConfig, room_name: str) -> dict[str, str] | None:
    """The backend's live presence for a room: ``{handle: kind}`` (``slim``/``lease``).

    ``None`` if the backend is unreachable — so ``ls`` can distinguish "no lease"
    from "couldn't ask." Best-effort, mirrors ``agent._is_resident``.
    """
    import httpx

    try:
        url = f"{config.server.api_url}/api/rooms/{room_name}/sessions/members"
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        members = resp.json().get("members", [])
    except Exception:
        return None
    return {
        str(m.get("handle", "")).lstrip("@").lower(): str(m.get("kind") or "?") for m in members
    }


def _reconcile_note(mycelium_kind: str | None, herdr_status: str | None) -> tuple[str, str]:
    """The three-way verdict for one binding → ``(text, colour)``.

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
    return ("—", "dim")


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

            hcolour = {
                "idle": "green",
                "done": "green",
                "working": "yellow",
                "blocked": "red",
            }.get(herdr_status or "", "dim")
            note, ncolour = _reconcile_note(myc_kind, herdr_status)
            myc_display = "[dim]?[/dim]" if members is None else (myc_kind or "[dim]absent[/dim]")
            table.add_row(
                m.room,
                f"@{m.handle}",
                m.pane,
                myc_display,
                f"[{hcolour}]{herdr_status or '—'}[/{hcolour}]",
                f"[{ncolour}]{note}[/{ncolour}]",
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


@doc_ref(
    usage="mycelium herdr enroll --workspace <id> --room <room> [--kind K] [--wake] [--dry-run]",
    desc="Enroll every live herdr agent in a workspace into a mycelium room.",
    group="agent",
)
@app.command("enroll")
def herdr_enroll(
    ctx: typer.Context,
    workspace: str = typer.Option(..., "--workspace", "-w", help="herdr workspace id, e.g. w2."),
    room: str | None = typer.Option(None, "--room", "-r", help="Room (defaults to active)."),
    kind: str | None = typer.Option(None, "--kind", help="Only agents of this herdr kind."),
    name_from: str = typer.Option(
        "tab", "--name-from", help="Handle source: 'tab' (tab name) or 'pane' (pane id)."
    ),
    prefix: str = typer.Option("", "--prefix", help="Handle prefix (e.g. 'agent-' to namespace)."),
    wake: bool = typer.Option(False, "--wake", help="Wake each enrolled agent to join now."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan without registering."),
) -> None:
    """Bind a herdr **workspace** to a mycelium **room** in one shot.

    A herdr workspace already groups agents that work together, so it's the
    natural unit to map onto a coordination space (design-doc Shape 2). For each
    live agent in the workspace this registers a ``claude_code`` manifest, binds
    handle↔pane, and — with ``--wake`` — wakes it to join. The handle is derived
    from the **tab name** by default (``--name-from pane`` to use the pane id),
    with collisions disambiguated by the pane suffix. Idempotent: re-running skips
    agents already registered + mapped.

    This only *drives* agents you already started in herdr; it never spawns panes.
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        bridge = _bridge()
        if not bridge.available():
            console.print("[yellow]herdr not reachable[/yellow] — cannot enroll.")
            raise typer.Exit(1)

        agents = [
            a
            for a in bridge.list_agents()
            if a.get("workspace_id") == workspace
            and a.get("pane_id")
            and (kind is None or a.get("agent") == kind)
        ]
        if not agents:
            console.print(
                f"[yellow]No live agents[/yellow] in workspace {workspace}"
                + (f" of kind {kind}" if kind else "")
                + "."
            )
            raise typer.Exit(1)

        # Reuse the exact manifest-registration path `agent create` uses.
        from mycelium.commands.agent import _load_manifest, _write_manifest
        from mycelium.integrations import AddOptions, get_integration

        tab_labels = bridge.tab_labels(workspace) if name_from == "tab" else {}
        sender = config.get_current_identity()
        table = Table(title=f"enroll {workspace} → {room_name}", show_lines=False)
        table.add_column("pane", style="cyan")
        table.add_column("tab", style="dim")
        table.add_column("handle", style="cyan")
        table.add_column("action")
        planned: list[tuple[str, str, str]] = []
        taken: set[str] = set()
        for a in agents:
            pane = str(a["pane_id"])
            tab_label = tab_labels.get(str(a.get("tab_id") or ""), "")
            handle = _derive_handle(
                tab_label=tab_label,
                pane_id=pane,
                prefix=prefix,
                name_from=name_from,
                taken=taken,
            )
            taken.add(handle)
            already = _load_manifest(room_name, handle) is not None
            mapped = bridge.registry.get(room_name, handle) is not None
            action = "skip (registered+mapped)" if already and mapped else "register + map"
            planned.append((pane, handle, action))
            tab_display = tab_label or "[dim]—[/dim]"
            if dry_run:
                table.add_row(pane, tab_display, f"@{handle}", f"[dim]{action}[/dim]")
                continue
            mapping = HerdrPaneMapping(
                room=room_name, handle=handle, pane=pane, kind=a.get("agent")
            )
            if not (already and mapped):
                if not already:
                    impl = get_integration("claude_code", cwd=a.get("cwd"))
                    manifest = impl.build_manifest(
                        handle=handle,
                        opts=AddOptions(room=room_name),
                        description=f"herdr-enrolled from {pane} ({a.get('agent')})",
                        allow_from=[],
                        owner=sender,
                    )
                    _write_manifest(config, room_name, manifest, created_by=sender)
                bridge.registry.set(mapping)
            woke = ""
            if wake and not dry_run:
                result = bridge.wake(
                    mapping,
                    build_wake_prompt(room_name, handle),
                    timeout_ms=config.herdr.wake_timeout_ms,
                )
                woke = " + woke" if result.ok else f" + wake failed ({result.detail})"
            table.add_row(pane, tab_display, f"@{handle}", f"[green]{action}[/green]{woke}")

        console.print(table)
        if dry_run:
            console.print("[dim]Dry run — nothing registered. Drop --dry-run to apply.[/dim]")
        else:
            console.print(
                f"[green]Enrolled[/green] {len(planned)} agent(s) into [cyan]{room_name}[/cyan]. "
                f"Inspect with [dim]mycelium herdr ls --room {room_name}[/dim]"
            )
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium herdr status",
    desc="Show whether herdr is installed and reachable.",
    group="agent",
)
@app.command("status")
def herdr_status(ctx: typer.Context) -> None:
    """Report herdr availability — the precondition for the wake path."""
    try:
        bridge = _bridge()
        if not bridge.binary_present():
            console.print("[yellow]herdr not installed[/yellow] — the wake layer is unavailable.")
            console.print(
                "[dim]Install from https://herdr.dev; mycelium works fine without it.[/dim]"
            )
            raise typer.Exit(1)
        if not bridge.available():
            console.print("[yellow]herdr installed but server unreachable.[/yellow]")
            raise typer.Exit(1)
        agents = bridge.list_agents()
        console.print(
            f"[green]herdr reachable[/green] — {len(agents)} live agent(s), "
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
                "[yellow]herdr not reachable[/yellow] — cannot wake; message stays on the cursor."
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
            console.print(f"[green]Woke[/green] @{mapping.handle} [dim]— {result.detail}[/dim]")
        else:
            console.print(f"[yellow]Not woken[/yellow] [dim]— {result.detail}[/dim]")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except HerdrError as e:
        console.print(f"[red]herdr error:[/red] {e}")
        raise typer.Exit(1) from None


def _collect_presence(bridge: HerdrBridge, room_filter: str | None) -> dict[str, dict[str, str]]:
    """Current herdr liveness for every mapped handle → ``{room: {handle: status}}``.

    Only mapped handles whose pane currently hosts a live agent are included; an
    unmapped/dead pane is simply omitted so its backend entry lapses on its TTL.
    """
    live = {
        str(a["pane_id"]): str(a.get("agent_status") or "unknown")
        for a in bridge.list_agents()
        if a.get("pane_id")
    }
    view: dict[str, dict[str, str]] = {}
    for m in bridge.registry.all():
        if room_filter and m.room != room_filter:
            continue
        status = live.get(m.pane)
        if status is not None:
            view.setdefault(m.room, {})[m.handle] = status
    return view


def _push_presence(
    config: MyceliumConfig, room: str, statuses: dict[str, str], ttl_s: float
) -> bool:
    """POST one room's herdr liveness to the backend. Best-effort → ``bool`` ok."""
    import httpx

    try:
        url = f"{config.server.api_url}/api/rooms/{room}/sessions/herdr-presence"
        resp = httpx.post(url, json={"statuses": statuses, "ttl_s": ttl_s}, timeout=5.0)
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

    try:
        url = f"{config.server.api_url}/api/rooms/{room}/sessions/herdr-wakes"
        resp = httpx.get(url, timeout=5.0)
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
            console.print(f"[yellow]↯ skip[/yellow] @{handle} [dim]— {result.detail}[/dim]")
    return woke


@doc_ref(
    usage="mycelium herdr sync [--room <room>] [--watch] [--interval N]",
    desc="Push herdr liveness to the backend so the UI can show idle/working/blocked.",
    group="agent",
)
@app.command("sync")
def herdr_sync(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Only sync this room."),
    watch: bool = typer.Option(False, "--watch", help="Keep polling and pushing on change."),
    interval: int = typer.Option(5, "--interval", help="Poll interval seconds (with --watch)."),
) -> None:
    """Mirror herdr's live agent states into the backend presence surface.

    The backend runs containerized and can't see the host's herdr socket, so this
    host-side bridge polls ``herdr agent list`` and pushes each mapped handle's
    state to the backend, which the frontend renders as a liveness badge. This is
    the honest home for a host-side loop after the cold-spawn daemon's removal: it
    only mirrors liveness — it never spawns or wakes agents.

    One-shot by default; ``--watch`` keeps it running (pushes on change, with a
    periodic heartbeat so entries don't lapse). Ctrl-C clears the overlay.
    """
    import time

    try:
        config = MyceliumConfig.load()
        room_filter = _resolve_room(config, room) if room else None
        bridge = _bridge()
        if not bridge.available():
            console.print("[yellow]herdr not reachable[/yellow] — nothing to sync.")
            raise typer.Exit(1)

        ttl_s = max(90.0, interval * 4.0)

        def push_all(view: dict[str, dict[str, str]]) -> int:
            ok = 0
            for r, statuses in view.items():
                if _push_presence(config, r, statuses, ttl_s):
                    ok += 1
            return ok

        view = _collect_presence(bridge, room_filter)
        pushed = push_all(view)
        total = sum(len(v) for v in view.values())
        for r in view:
            _drain_wakes(config, bridge, r)  # handle any tags waiting on the queue
        console.print(
            f"[green]Synced[/green] {total} agent state(s) across {pushed} room(s)."
            + ("" if watch else " [dim](one-shot; --watch to keep live)[/dim]")
        )
        if not watch:
            return

        console.print(
            f"[dim]Watching herdr every {interval}s (presence up, wakes down) — "
            f"Ctrl-C to stop.[/dim]"
        )
        last: dict[str, dict[str, str]] = view
        last_push = time.monotonic()
        rooms_seen = set(view)
        try:
            while True:
                time.sleep(interval)
                view = _collect_presence(bridge, room_filter)
                rooms_seen |= set(view)
                # Drain wake-on-mention every tick — tags are time-sensitive.
                for r in rooms_seen:
                    _drain_wakes(config, bridge, r)
                # Push presence on change, or heartbeat every ~half-TTL to keep live.
                changed = view != last
                if changed or (time.monotonic() - last_push) >= ttl_s / 2:
                    push_all(view)
                    # Clear rooms that dropped to empty so their badges disappear.
                    for r in rooms_seen - set(view):
                        _push_presence(config, r, {}, ttl_s)
                    last, last_push = view, time.monotonic()
                    if changed:
                        total = sum(len(v) for v in view.values())
                        console.print(f"[dim]↻ pushed {total} state(s)[/dim]")
        except KeyboardInterrupt:
            for r in rooms_seen:
                _push_presence(config, r, {}, ttl_s)
            console.print("\n[dim]Stopped — cleared herdr overlay.[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None
