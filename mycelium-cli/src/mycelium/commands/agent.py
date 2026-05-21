# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Agent commands — name an addressable, durable agent inside a room.

An agent is just two memory entries plus an adapter route:

    <room>/agents/<handle>            ← manifest (this command writes it)
    <room>/agents/<handle>/notes      ← persistent brain, agent-curated
    <room>/agents/<handle>/log/<ts>   ← per-invocation transcript (daemon writes)

The corresponding daemon (``mycelium-cc-daemon``, installed via
``mycelium adapter add claude-code --step=daemon``) watches each room's SSE
stream, dispatches ``@handle`` mentions to the right runtime, and posts the
reply back to the room as ``@handle``.

These commands are typing comfort on top of ``memory`` and ``room send``:
``agent create``/``add`` write ``memory set agents/<handle>`` with
validation (``create`` = greenfield, Mycelium-controlled; ``add`` = adopt an
agent that already exists in your OpenClaw gateway, interactively or by id),
``agent invoke`` is ``room send "@handle ..."``. The primitives don't change.
"""

from __future__ import annotations

import json as json_module
import sys
from datetime import UTC, datetime

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.integrations import AddOptions, Integration, get_adapter
from mycelium.integrations.openclaw import OpenClawIntegration
from mycelium.protocol import AGENT_ADAPTERS, AgentManifest

app = typer.Typer(
    help=(
        "Name an addressable agent inside a room. "
        "An agent is a memory entry plus an adapter route — `agent create` (new) "
        "or `agent add` (adopt existing) writes the manifest, `agent invoke` "
        "sends an @handle message into its home room."
    ),
    no_args_is_help=True,
)
console = Console()


def _typed_client(config: MyceliumConfig):
    from mycelium_backend_client import Client

    return Client(base_url=config.server.api_url, raise_on_unexpected_status=True)


def _resolve_room(config: MyceliumConfig, room: str | None) -> str:
    if room:
        return room
    active = getattr(config.rooms, "active", None)
    if active:
        return active
    typer.secho(
        "No room specified and no active room set. "
        "Use --room or `mycelium config set rooms.active <name>`.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(1)


def _load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    """Read the manifest off the local filesystem and rehydrate the model."""
    room_dir = get_room_dir(room_name)
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError:
        return None


def _write_manifest(
    config: MyceliumConfig, room_name: str, manifest: AgentManifest, created_by: str
) -> None:
    """Upsert the manifest into the backend AND mirror it to the local filesystem.

    The daemon resolves manifests by reading the local filesystem (single-machine
    v0), so the backend write alone isn't enough — we mirror via the same
    ``filesystem.write_memory`` helper that the rest of the CLI uses for local
    copies of API-written memories.
    """
    from mycelium.filesystem import write_memory
    from mycelium_backend_client.api.memory import (
        create_memories_api_rooms_room_name_memory_post as create_api,
    )
    from mycelium_backend_client.models import MemoryBatchCreate, MemoryCreate

    body = manifest.model_dump(exclude={"handle"})
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False).strip()
    # embed=False: a manifest is a registry/config entry, not room knowledge.
    # Embedding it pollutes `memory search` (and synthesis) with roster noise.
    item = MemoryCreate(
        key=manifest.memory_key,
        value=yaml_body,
        created_by=created_by,
        embed=False,
        tags=["agent-manifest"],
    )
    batch = MemoryBatchCreate(items=[item])
    with _typed_client(config) as client:
        result = create_api.sync(room_name=room_name, client=client, body=batch)

    # Mirror locally so `agent ls/show/invoke` + the daemon's filesystem lookup
    # find the manifest without a round-trip.
    room_dir = get_room_dir(room_name)
    version = 1
    if result and isinstance(result, list) and result:
        version = getattr(result[0], "version", 1) or 1
    write_memory(
        room_dir,
        manifest.memory_key,
        yaml_body,
        created_by=created_by,
        version=version,
        tags=["agent-manifest"],
    )


# ── create (greenfield) ──────────────────────────────────────────────────────


def _persist_and_describe(
    *,
    impl: Integration,
    manifest: AgentManifest,
    config: MyceliumConfig,
    room_name: str,
    handle_flag: str,
    verb: str,
) -> None:
    """Shared tail: run runtime side effects, persist the manifest, print."""
    opts = AddOptions(room=room_name)
    # Runtime side effects FIRST — a failure here aborts without leaving a
    # dangling manifest.
    impl.register(manifest=manifest, config=config, opts=opts)
    _write_manifest(config, room_name, manifest, created_by=handle_flag)
    console.print(
        f"\n[green]Agent {verb}:[/green] [cyan]@{manifest.handle}[/cyan] "
        f"in room [bold]{room_name}[/bold]"
    )
    for line in impl.describe(manifest, room=room_name):
        console.print(line)


@doc_ref(
    usage="mycelium agent create <handle> --adapter <name> [--cwd <path>]",
    desc=(
        "Create a new, Mycelium-controlled agent in a room (greenfield). "
        "<code>claude_code</code> agents are cold-spawned by the cc-daemon; "
        "<code>openclaw</code> agents are newly created in the OpenClaw "
        "gateway. To adopt an agent that already exists, use "
        "<code>mycelium agent add</code>."
    ),
    group="agent",
)
@app.command("create")
def agent_create(
    ctx: typer.Context,
    handle: str = typer.Argument(
        ..., help="Agent handle (lowercase slug, e.g. 'release-agent'). Used as @-mention target."
    ),
    adapter: str = typer.Option(
        "claude_code",
        "--adapter",
        help=f"Adapter that hosts this agent. Known: {', '.join(sorted(AGENT_ADAPTERS))}.",
    ),
    cwd: str | None = typer.Option(
        None,
        "--cwd",
        help="claude_code: working dir `claude -p` runs in (required for that adapter).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="openclaw: model for the new agent (else openclaw default).",
    ),
    openclaw_profile: str | None = typer.Option(
        None,
        "--openclaw-profile",
        help="openclaw: target a named OpenClaw profile (e.g. 'work' → ~/.openclaw-work/).",
    ),
    copy_auth_from: str | None = typer.Option(
        None,
        "--copy-auth-from",
        help=(
            "openclaw: copy auth-profiles.json from this existing OpenClaw "
            "agent so the new one can authenticate (it's created with no "
            "creds otherwise). Duplicates a secret — choose deliberately."
        ),
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to register in (defaults to active room)."
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="One-paragraph statement of what this agent does."
    ),
    budget: float = typer.Option(
        5.0, "--budget", help="claude_code: monthly USD spend cap enforced by the daemon."
    ),
    allow_from: str | None = typer.Option(
        None,
        "--allow-from",
        help="Comma-separated sender handles allowed to invoke (e.g. '@julia,@docs-agent').",
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Create a new, Mycelium-controlled agent in a room.

    Greenfield: for openclaw this spins up a *new* OpenClaw agent. To wire
    up agents that already exist in your OpenClaw gateway, use
    ``mycelium agent add`` (interactive picker) instead.

    Examples:
        # claude_code (cold-spawned by the cc-daemon)
        mycelium agent create release-agent --cwd ~/repos/mycelium

        # openclaw — create a fresh OpenClaw agent named @planner
        mycelium agent create planner --adapter openclaw \\
            --description "Sprint planner, optimizes for shipping speed"
    """
    try:
        if adapter not in AGENT_ADAPTERS:
            known = ", ".join(sorted(AGENT_ADAPTERS))
            typer.secho(f"Unknown adapter '{adapter}'. Known: {known}.", fg=typer.colors.RED)
            raise typer.Exit(1)

        allow_list: list[str] = []
        if allow_from:
            allow_list = [a.strip() for a in allow_from.split(",") if a.strip()]

        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        # No openclaw_agent → openclaw_created=True (greenfield) by the
        # manifest validator. That is the whole point of `create`.
        impl = get_adapter(
            adapter,
            cwd=cwd,
            model=model,
            openclaw_profile=openclaw_profile,
            copy_auth_from=copy_auth_from,
        )

        try:
            manifest = impl.build_manifest(
                handle=handle,
                opts=AddOptions(room=room_name),
                description=description,
                budget=budget,
                allow_from=allow_list,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid agent manifest: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        _persist_and_describe(
            impl=impl,
            manifest=manifest,
            config=config,
            room_name=room_name,
            handle_flag=handle_flag,
            verb="created",
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── add (adopt existing — interactive picker, or one by id) ───────────────────


@doc_ref(
    usage="mycelium agent add [<openclaw-id>] [--room <room>]",
    desc=(
        "Adopt agents that already exist in your OpenClaw gateway. With no "
        "argument in a terminal it opens an interactive picker that "
        "discovers local OpenClaw agents, installs the adapter if needed, "
        "and wires the selected ones into a room. Pass an id to adopt one "
        "non-interactively. To create a new agent, use "
        "<code>mycelium agent create</code>."
    ),
    group="agent",
)
@app.command("add")
def agent_add(
    ctx: typer.Context,
    handle: str | None = typer.Argument(
        None,
        help="Existing OpenClaw agent id to adopt. Omit (in a TTY) for the interactive picker.",
    ),
    openclaw_profile: str | None = typer.Option(
        None,
        "--openclaw-profile",
        help="openclaw: target a named OpenClaw profile (e.g. 'work' → ~/.openclaw-work/).",
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to register in (defaults to active room)."
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="One-paragraph statement (single-adopt only)."
    ),
    budget: float = typer.Option(5.0, "--budget", help="Monthly USD spend cap."),
    allow_from: str | None = typer.Option(
        None, "--allow-from", help="Comma-separated sender handles allowed to invoke."
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Adopt agents that already exist in your OpenClaw gateway.

    No argument + a terminal → interactive picker (discover → select →
    install adapter if needed → wire into a room, one gateway restart).
    ``mycelium agent add <openclaw-id>`` adopts a single agent
    non-interactively. Greenfield agents: ``mycelium agent create``.
    """
    try:
        config = MyceliumConfig.load()

        if handle is None:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                typer.secho(
                    "mycelium agent add needs an OpenClaw agent id when "
                    "non-interactive.\n"
                    "  Interactive picker: run it in a terminal.\n"
                    "  Adopt one: mycelium agent add <openclaw-id> [--room <room>]\n"
                    "  Create new: mycelium agent create <handle> --adapter ...",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            _onboard_wizard(
                ctx,
                config=config,
                openclaw_profile=openclaw_profile,
                room_opt=room,
                handle_flag=handle_flag,
            )
            return

        # Single non-interactive adopt: handle IS the existing OpenClaw id.
        allow_list: list[str] = [a.strip() for a in (allow_from or "").split(",") if a.strip()]
        room_name = _resolve_room(config, room)
        impl = get_adapter("openclaw", openclaw_agent=handle, openclaw_profile=openclaw_profile)
        try:
            manifest = impl.build_manifest(
                handle=handle,
                opts=AddOptions(room=room_name),
                description=description,
                budget=budget,
                allow_from=allow_list,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid agent manifest: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc
        _persist_and_describe(
            impl=impl,
            manifest=manifest,
            config=config,
            room_name=room_name,
            handle_flag=handle_flag,
            verb="adopted",
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


def _pick_room(config: MyceliumConfig) -> str | None:
    """Fetch rooms from the backend and let the user pick one (or create a
    new one). Returns a room name guaranteed to exist on the backend, or
    None if the user aborted.

    Doing this before any side effects also closes the half-applied footgun:
    the manifest write 404s on a missing room, but only *after* the channel
    config + gateway restart — guaranteeing existence here avoids that.
    """
    import questionary

    from mycelium_backend_client.api.rooms import (
        create_room_api_rooms_post as create_api,
    )
    from mycelium_backend_client.api.rooms import (
        list_rooms_api_rooms_get as list_api,
    )
    from mycelium_backend_client.models import HTTPValidationError, RoomCreate

    rooms: list[str] = []
    try:
        with _typed_client(config) as client:
            result = list_api.sync(client=client, limit=200)
        if result and not isinstance(result, HTTPValidationError):
            # Backend returns rooms created_at DESC (newest first); preserve
            # that rather than re-sorting alphabetically (matches the
            # dashboard's CREATED ordering). Dedupe, keep order.
            seen: set[str] = set()
            for r in result:
                nm = str(r.to_dict().get("name") or "")
                if nm and nm not in seen:
                    seen.add(nm)
                    rooms.append(nm)
    except Exception as exc:  # noqa: BLE001 — backend optional/unreachable
        console.print(f"[yellow]Could not list rooms ({exc}).[/yellow]")

    active = getattr(config.rooms, "active", None)
    if active and active in rooms:  # most likely target → pin to top
        rooms = [active, *[r for r in rooms if r != active]]
    new_sentinel = "\x00new"

    if not rooms:
        name = questionary.text(
            "No rooms yet — name a new room to create:", default="default"
        ).ask()
    else:
        room_choices: list = [
            questionary.Choice(title=rn + ("  (active)" if rn == active else ""), value=rn)
            for rn in rooms
        ]
        room_choices.append(questionary.Separator())
        room_choices.append(questionary.Choice(title="＋ create a new room…", value=new_sentinel))
        room_choices.append(questionary.Separator("  ↑/↓ move · enter select"))
        picked = questionary.select(
            "Add agents to which room?",
            choices=room_choices,
            default=active if active in rooms else None,
            instruction="",
            use_pagination=True,  # long room lists scroll a viewport
        ).ask()
        if picked is None:
            return None
        if picked != new_sentinel:
            return picked
        name = questionary.text("New room name:").ask()

    if not name:
        return None
    try:
        with _typed_client(config) as client:
            create_api.sync(client=client, body=RoomCreate(name=name))
        console.print(f"[green]created room[/green] [bold]{name}[/bold]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not create room '{name}': {exc}[/red]")
        return None
    return name


def _onboard_wizard(
    ctx: typer.Context,
    *,
    config: MyceliumConfig,
    openclaw_profile: str | None,
    room_opt: str | None,
    handle_flag: str,
) -> None:
    """Interactive brownfield onboarding: discover → pick → ensure adapter →
    batch-adopt into a room (one gateway restart)."""
    import questionary

    impl = OpenClawIntegration(openclaw_profile=openclaw_profile)
    discovered = impl.discover_local_agents()
    if not discovered:
        console.print(
            "[yellow]No OpenClaw agents found[/yellow] in "
            f"{'~/.openclaw' if not openclaw_profile else f'~/.openclaw-{openclaw_profile}'}.\n"
            "  Create one with [cyan]openclaw agents add[/cyan], or a fresh "
            "Mycelium-managed one with [cyan]mycelium agent create[/cyan]."
        )
        return

    # Target room first — a manifest only exists inside a room. Fetch rooms
    # from the backend and let the user pick (or create) one; guarantees the
    # room exists before any side effects.
    if room_opt:
        room_name: str | None = room_opt
    else:
        room_name = _pick_room(config)
    if not room_name:
        console.print("[yellow]No room — aborted.[/yellow]")
        return

    # Mark agents already registered in this room so they aren't re-added.
    choices: list = []
    for a in discovered:
        aid = a["id"]
        already = _load_manifest(room_name, aid) is not None
        label = f"{aid}  ·  openclaw" + (f"  ·  {a['model']}" if a["model"] else "")
        choices.append(
            questionary.Choice(
                title=label + ("  (already added)" if already else ""),
                value=aid,
                disabled="already in room" if already else None,
            )
        )
    # Key hint UNDER the list (questionary renders `instruction` on the
    # question line; a trailing Separator is the only place it shows below
    # the choices). Suppress the verbose default top instruction.
    choices.append(
        questionary.Separator("  ↑/↓ move · space select · a toggle all · enter confirm")
    )

    selected: list[str] = (
        questionary.checkbox(
            f"Select OpenClaw agents to add to room '{room_name}'",
            choices=choices,
            instruction="",
            use_pagination=True,  # long agent lists scroll a viewport
        ).ask()
        or []
    )
    if not selected:
        console.print("[dim]Nothing selected — aborted.[/dim]")
        return

    # Ensure the openclaw adapter is installed (it owns the dispatch path).
    if "openclaw" not in config.adapters:
        proceed = questionary.confirm(
            "The openclaw adapter isn't installed (required to dispatch "
            "these agents). Install it now?",
            default=True,
        ).ask()
        if not proceed:
            console.print(
                "[yellow]openclaw adapter is required — aborted.[/yellow] "
                "Install later with: [cyan]mycelium adapter add openclaw[/cyan]"
            )
            return
        console.print("[dim]Installing openclaw adapter…[/dim]")
        get_adapter("openclaw", openclaw_profile=openclaw_profile).install(
            config=config,
            verbose=False,
            profile=openclaw_profile,
            container=None,
            reinstall=False,
        )
        record: dict = {
            "type": "openclaw",
            "installed_at": datetime.now(UTC).isoformat(),
            "api_url": config.server.api_url,
        }
        if openclaw_profile:
            record["openclaw_profile"] = openclaw_profile
        config.adapters["openclaw"] = record
        config.save()
        console.print("[green]openclaw adapter installed.[/green]")

    # Build + validate manifests (adopt mode → openclaw_created=False).
    valid: list[str] = []
    manifests = []
    for aid in selected:
        try:
            m = get_adapter(
                "openclaw", openclaw_agent=aid, openclaw_profile=openclaw_profile
            ).build_manifest(
                handle=aid,
                opts=AddOptions(room=room_name),
                description="",
                budget=5.0,
                allow_from=[],
            )
        except ValidationError as exc:
            console.print(f"  [yellow]skip {aid}[/yellow]: {exc}")
            continue
        valid.append(aid)
        manifests.append(m)
    if not valid:
        console.print("[yellow]No valid agents to add — aborted.[/yellow]")
        return

    # Channel-register all, then ONE gateway restart.
    impl.register_adopted_batch(valid, room=room_name, backend_url=config.server.api_url)
    for m in manifests:
        _write_manifest(config, room_name, m, created_by=handle_flag)

    console.print(
        f"\n[green]Added {len(valid)} agent"
        f"{'' if len(valid) == 1 else 's'} to[/green] [bold]{room_name}[/bold]: "
        + ", ".join(f"[cyan]@{h}[/cyan]" for h in valid)
    )
    console.print(
        "[dim]Invoke with[/dim] "
        f"[cyan]@{valid[0]} …[/cyan] [dim]in the room, or[/dim] "
        f'[cyan]mycelium agent invoke {valid[0]} "…"[/cyan]'
    )


# ── ls ───────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent ls [--room <room>]",
    desc="List all registered agents in a room.",
    group="agent",
)
@app.command("ls")
def agent_ls(
    ctx: typer.Context,
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """List registered agents in a room."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        room_dir = get_room_dir(room_name)

        entries = list_memories(room_dir, prefix="agents/", limit=200)
        # Drop notes + log children — manifests only live at agents/<handle>
        # without further path segments.
        manifests: list[AgentManifest] = []
        for key, _meta, _content in entries:
            handle = key.removeprefix("agents/")
            if "/" in handle:
                continue
            m = _load_manifest(room_name, handle)
            if m is not None:
                manifests.append(m)

        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            typer.echo(
                json_module.dumps([m.model_dump() for m in manifests], indent=2, default=str)
            )
            return

        if not manifests:
            console.print(f"[dim]No agents registered in {room_name}.[/dim]")
            console.print(
                f"  Create one with: mycelium agent create <handle> --cwd <path> --room {room_name}"
            )
            return

        table = Table(title=f"{room_name} — agents", show_lines=False)
        table.add_column("Handle", style="cyan", no_wrap=True)
        table.add_column("Adapter", style="magenta")
        table.add_column("Cwd")
        table.add_column("Budget", justify="right")
        table.add_column("Description", overflow="fold")
        for m in manifests:
            table.add_row(
                f"@{m.handle}",
                m.adapter,
                m.cwd,
                f"${m.budget_usd_per_month:.2f}/mo",
                (m.description or "")[:80],
            )
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── show ─────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent show <handle> [--room <room>]",
    desc="Show an agent's manifest, notes, and most recent invocation log.",
    group="agent",
)
@app.command("show")
def agent_show(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
) -> None:
    """Inspect a registered agent — manifest + notes + last invocation."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)
        room_dir = get_room_dir(room_name)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.")
            raise typer.Exit(1)

        console.print(f"[bold cyan]@{manifest.handle}[/bold cyan]  [dim]({manifest.adapter})[/dim]")
        console.print(f"  cwd: {manifest.cwd}")
        console.print(f"  budget: ${manifest.budget_usd_per_month:.2f}/mo")
        if manifest.allow_from:
            console.print(f"  allow_from: {', '.join(manifest.allow_from)}")
        if manifest.description:
            console.print(f"\n[bold]description[/bold]\n{manifest.description}")

        notes_result = read_memory(room_dir, manifest.notes_key)
        if notes_result is not None:
            _, notes_content = notes_result
            console.print("\n[bold]notes[/bold]")
            console.print(notes_content)
        else:
            console.print(
                f"\n[dim]No notes yet. Seed with: "
                f'mycelium memory set {manifest.notes_key} "..." --room {room_name}[/dim]'
            )

        from mycelium.daemon.config import daemon_invocation_log_dir

        log_dir = daemon_invocation_log_dir(room_name, manifest.handle)
        log_files = sorted(log_dir.glob("*.json"), reverse=True)
        if log_files:
            try:
                import json as _json

                entry = _json.loads(log_files[0].read_text())
                ts = str(entry.get("ts", "")).replace("T", " ").replace("Z", "")
                console.print(f"\n[bold]last invocation[/bold]  [dim]{ts}[/dim]")
                console.print(f"  {entry.get('sender', '?')} → {entry.get('prompt', '')[:120]}")
                ok = entry.get("ok")
                console.print(
                    f"  [{'green' if ok else 'red'}]"
                    f"{'ok' if ok else 'error'}[/]"
                    f" · {entry.get('duration_s', 0)}s · ${entry.get('cost_usd', 0):.4f}"
                )
                reply = entry.get("final_message") or ""
                if reply:
                    preview = reply[:400]
                    console.print(f"  reply: {preview}{'…' if len(reply) > 400 else ''}")
            except (OSError, ValueError):
                console.print(f"\n[dim]Last invocation log unreadable at {log_files[0]}[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── invoke ───────────────────────────────────────────────────────────────────


@doc_ref(
    usage='mycelium agent invoke <handle> "<prompt>" [--room <room>]',
    desc=(
        "Send an addressed message to a registered agent. "
        'Desugars to <code>mycelium room send "@handle &lt;prompt&gt;"</code>.'
    ),
    group="agent",
)
@app.command("invoke")
def agent_invoke(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle (without leading @)"),
    prompt: str = typer.Argument(..., help="Message body to send the agent."),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to send into (defaults to active room)."
    ),
    handle_flag: str | None = typer.Option(
        None, "--as", "-H", help="Your sender handle (defaults to identity config)."
    ),
) -> None:
    """Send an @-addressed message to a registered agent.

    Typing comfort over `mycelium room send "@handle ..."`. The daemon picks
    up the message on its SSE subscription and dispatches it to the right
    adapter.

    Examples:
        mycelium agent invoke release-agent "pull latest, new release"
        mycelium agent invoke docs-agent "regen the cli reference"
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(
                f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.\n"
                f"  Create one with: mycelium agent create {handle} --cwd <path> --room {room_name}"
            )
            raise typer.Exit(1)

        sender_handle = handle_flag or config.get_current_identity()
        content = f"@{manifest.handle} {prompt}"

        from mycelium_backend_client.api.messages import (
            send_message_api_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            body = MessageCreate(
                sender_handle=sender_handle,
                message_type="broadcast",
                content=content,
            )
            send_api.sync(room_name=room_name, client=client, body=body)

        console.print(
            f"[green]Sent[/green] [dim]({sender_handle} → [/dim]"
            f"[cyan]@{manifest.handle}[/cyan][dim] in {room_name})[/dim]"
        )
        console.print(f"  {prompt[:200]}")
        console.print(
            f"\n[dim]The daemon will dispatch via {manifest.adapter} and reply in "
            f"{room_name} as @{manifest.handle}.[/dim]"
        )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── rm ───────────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium agent rm <handle> [--room <room>] [--full] [--force]",
    desc=(
        "Unregister an agent. Default keeps the underlying runtime; "
        "<code>--full</code> also destroys a Mycelium-created OpenClaw agent "
        "(requires confirmation unless <code>-y</code>)."
    ),
    group="agent",
)
@app.command("rm")
def agent_rm(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
    room: str | None = typer.Option(None, "--room", "-r", help="Room name"),
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Destructive: also tear down the underlying runtime. For openclaw "
            "create-mode agents this runs `openclaw agents remove` + deletes the "
            "workspace. Adopted agents are never destroyed."
        ),
    ),
    force: bool = typer.Option(False, "--force", "-f", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Unregister an agent.

    **Default (safe):** deletes the manifest. For openclaw, also drops the
    handle from the mycelium-room channel and restarts the gateway — but
    leaves the OpenClaw agent itself running. Notes/logs are preserved so the
    agent can be re-registered later.

    **--full (destructive):** additionally destroys the underlying runtime.
    Only openclaw *create-mode* agents are destroyed (`openclaw agents
    remove` + workspace delete); agents you *adopted* are never destroyed —
    --full just unregisters them, same as default. Always prompts unless
    -y/--force.
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        manifest = _load_manifest(room_name, handle)
        if manifest is None:
            console.print(f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.")
            raise typer.Exit(1)

        impl = get_adapter(manifest.adapter)
        will_destroy = impl.will_destroy_runtime(manifest, full=full)

        if not force:
            if will_destroy:
                console.print(
                    f"[red]Destructive:[/red] this will [bold]permanently destroy[/bold] "
                    f"the underlying runtime for [cyan]@{handle}[/cyan] "
                    f"(adapter: {manifest.adapter}), unregister it, and delete "
                    f"the manifest."
                )
                prompt = f"Destroy @{handle} and its runtime?"
            elif full and manifest.adapter == "openclaw" and not manifest.openclaw_created:
                console.print(
                    f"[yellow]@{handle} was adopted, not created by Mycelium — "
                    f"--full will NOT destroy OpenClaw agent "
                    f"'{manifest.openclaw_agent}'.[/yellow] It will only be "
                    f"unregistered from the channel + manifest."
                )
                prompt = f"Unregister @{handle} from room '{room_name}'?"
            else:
                prompt = f"Unregister @{handle} from room '{room_name}'? (notes + logs preserved)"
            if not typer.confirm(prompt):
                raise typer.Exit(0)

        # 1. Runtime teardown (adapter-specific). No-op for claude_code.
        impl.destroy(manifest=manifest, config=config, room=room_name, full=full)

        # 2. Delete the manifest (backend + local mirror).
        from mycelium_backend_client.api.memory import (
            delete_memory_api_rooms_room_name_memory_key_delete as delete_api,
        )

        with _typed_client(config) as client:
            delete_api.sync_detailed(room_name=room_name, key=manifest.memory_key, client=client)
        local = get_room_dir(room_name) / f"{manifest.memory_key}.md"
        if local.exists():
            local.unlink()

        verb = "Destroyed" if will_destroy else "Unregistered"
        console.print(f"[green]{verb}:[/green] @{handle} from {room_name}")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# Re-export for completeness — daemon and doctor reuse these.
__all__ = [
    "_load_manifest",
    "app",
]
