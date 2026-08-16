# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Agent commands — name an addressable, durable agent inside a room.

An agent is just two memory entries:

    <room>/agents/<handle>            ← manifest (this command writes it)
    <room>/agents/<handle>/notes      ← persistent brain, agent-curated

The agent's *runtime* is the user's own resident session — a Claude Code or
Cursor session kept woken with ``mycelium await --loop``, which participates via
``await``/``respond``. Mycelium names the agent and installs its skill; it does
not run the process.

These commands are typing comfort on top of ``memory`` and ``room send``:
``agent create`` writes ``memory set agents/<handle>`` with validation,
``agent invoke`` is ``room send "@handle ..."``. The primitives don't change.
"""

from __future__ import annotations

import json as json_module
import logging
import sys
from pathlib import Path

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mycelium.client import hub_client
from mycelium.client import typed_client as _typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error
from mycelium.filesystem import get_room_dir, list_memories, read_memory
from mycelium.integrations import AddOptions, Integration, get_adapter
from mycelium.protocol import AGENT_ADAPTERS, AgentManifest

app = typer.Typer(
    help=(
        "Name an addressable agent inside a room. "
        "An agent is a memory entry plus an adapter route: `agent create` "
        "writes the manifest, `agent invoke` "
        "sends an @handle message into its home room."
    ),
    no_args_is_help=True,
)
console = Console()


def _bail_root_owned(target: Path, blocking: Path, owner_name: str) -> None:
    """Print a chown-guidance error and exit 1.

    Used when writing under ``~/.mycelium/`` would fail because some ancestor
    of *target* is owned by a different user (typically root, from an earlier
    sudo step or a containerized side-process). The previous symptom was a
    raw ``PermissionError`` with no hint about what to do — this surfaces the
    one-line fix every time it would have happened.
    """
    typer.secho(f"\n  ✗ Cannot write to {target}", fg=typer.colors.RED, err=True)
    typer.echo(f"    {blocking} is owned by {owner_name}, not the current user.", err=True)
    typer.echo("", err=True)
    typer.echo(
        "    This usually happens when an earlier step ran as a different",
        err=True,
    )
    typer.echo(
        "    user (sudo, or a systemd service running as root).",
        err=True,
    )
    typer.echo("", err=True)
    typer.echo("    Fix with:", err=True)
    typer.echo("", err=True)
    typer.echo("      sudo chown -R $USER ~/.mycelium", err=True)
    typer.echo("", err=True)
    raise typer.Exit(1)


def _owner_uid(path: Path) -> int | None:
    """Return st_uid for *path*, or ``None`` if stat fails. Patchable in tests."""
    try:
        return path.stat().st_uid
    except OSError:
        return None


def _check_writable_or_bail(target: Path) -> None:
    """Bail out with chown guidance if any ancestor of *target* isn't ours.

    Walks up to the closest existing ancestor of *target* and checks its
    ``st_uid`` against ``os.getuid()``. Mismatch → :func:`_bail_root_owned`.
    Windows has no uid concept; this no-ops there. Stat failures are
    swallowed (let the real write raise its own error).
    """
    import os

    if os.name == "nt":
        return
    uid = os.getuid()
    p = target
    while not p.exists():
        if p.parent == p:
            return
        p = p.parent
    owner_uid = _owner_uid(p)
    if owner_uid is None or owner_uid == uid:
        return
    try:
        import pwd

        owner_name = pwd.getpwuid(owner_uid).pw_name
    except (KeyError, ImportError):
        owner_name = f"uid {owner_uid}"
    _bail_root_owned(target, p, owner_name)


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


_log = logging.getLogger(__name__)


def _load_manifest(room_name: str, handle: str) -> AgentManifest | None:
    """Read the manifest off the local filesystem and rehydrate the model.

    Returns ``None`` for both "file missing" and "file present but unreadable"
    — callers can't tell the difference from the return value, but a corrupt
    manifest is logged at WARNING so it never fails silently. Without this,
    a bad YAML or schema mismatch looks identical to "agent not registered"
    and the user re-runs ``agent create`` over their own broken file.
    """
    room_dir = get_room_dir(room_name)
    path = room_dir / "agents" / f"{handle}.md"
    result = read_memory(room_dir, f"agents/{handle}")
    if result is None:
        return None
    _, content = result
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        _log.warning("manifest %s: invalid YAML — %s", path, exc)
        return None
    if not isinstance(data, dict):
        _log.warning("manifest %s: expected a YAML mapping, got %s", path, type(data).__name__)
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError as exc:
        _log.warning("manifest %s: schema validation failed — %s", path, exc)
        return None


def _is_resident(config: MyceliumConfig, room_name: str, handle: str) -> bool:
    """True if a runtime is currently present in the room for ``handle``.

    Best-effort: queries the backend's live presence set (SLIM sockets + server-
    held ``await`` leases). A network/parse failure returns ``False`` so the
    caller falls back to the honest "not resident — queued" message rather than
    claiming liveness it can't confirm.
    """
    try:
        with hub_client(config, timeout=5.0) as client:
            resp = client.get(f"/api/rooms/{room_name}/sessions/members")
        resp.raise_for_status()
        members = resp.json().get("members", [])
    except Exception:
        return False
    norm = handle.lstrip("@").lower()
    return any(str(m.get("handle", "")).lstrip("@").lower() == norm for m in members)


def _room_manifests(room_name: str) -> list[AgentManifest]:
    """Every agent manifest registered in a room (skips notes + log children)."""
    room_dir = get_room_dir(room_name)
    out: list[AgentManifest] = []
    for key, _meta, _content in list_memories(room_dir, prefix="agents/", limit=500):
        handle = key.removeprefix("agents/")
        if "/" in handle:
            continue
        m = _load_manifest(room_name, handle)
        if m is not None:
            out.append(m)
    return out


def load_owned_agents(*, owner: str) -> list[tuple[str, AgentManifest]]:
    """Agents owned by ``owner`` across every local room."""
    from mycelium.filesystem import list_room_names

    owner = owner.strip().lstrip("@").lower()
    owned: list[tuple[str, AgentManifest]] = []
    for room_name in list_room_names():
        for m in _room_manifests(room_name):
            if m.owner == owner:
                owned.append((room_name, m))
    return owned


def _warn_unknown_principal(manifest: AgentManifest) -> None:
    """Warn (never fail) when an agent's owner has no user record.

    The binding is self-asserted, so a dangling owner is a soft signal, not an
    error — it just nudges the user to register the principal so 'my agents'
    has something to resolve.
    """
    if not manifest.owner:
        return
    from mycelium.commands.user import load_user

    if load_user(manifest.owner) is None:
        console.print(
            f"[yellow]note:[/yellow] owner '@{manifest.owner}' has no user record. "
            f'Register it with: mycelium user create {manifest.owner} --name "…"'
        )


def _load_manifest_remote(client, room_name: str, handle: str) -> AgentManifest | None:
    """Fetch a manifest from the backend memory API and rehydrate the model.

    Used as a fall-through when the local mirror doesn't have it — typically
    a hub→spoke (or spoke→hub) cross-host invocation, where the agent was
    registered on a different machine and this host hasn't materialized
    the manifest into its local room directory yet.

    The manifest is stored at ``agents/<handle>`` as a YAML body (see
    ``_write_manifest``), so we just need to download the memory entry and
    re-parse it. Returns ``None`` for "not on the backend either" or any
    transient error — the caller re-uses the same friendly "no agent named
    …" message that fires for a true missing agent.
    """
    from mycelium_backend_client.api.memory import (
        get_memory_api_rooms_room_name_memory_key_get as get_api,
    )

    try:
        result = get_api.sync(
            room_name=room_name,
            key=f"agents/{handle}",
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 — log and treat as "not found"
        _log.warning("backend manifest fetch failed for %s/%s: %s", room_name, handle, exc)
        return None

    if result is None:
        return None
    # The endpoint returns ``HTTPValidationError | MemoryRead | None`` for
    # 200/404/422; only ``MemoryRead`` carries a usable manifest body.
    #
    # The body itself can land in any of three shapes depending on how the
    # backend serialised it (and whether the generated client kept the
    # convenience ``content_text`` field): prefer ``content_text`` (the
    # already-flattened YAML string), fall back to ``value`` if it's a
    # plain ``str``, and finally peek inside ``MemoryReadValueType0``
    # (a dict-like with ``text`` populated by the backend).
    yaml_body: str | None = None
    content_text = getattr(result, "content_text", None)
    if isinstance(content_text, str) and content_text:
        yaml_body = content_text
    if yaml_body is None:
        value = getattr(result, "value", None)
        if isinstance(value, str):
            yaml_body = value
        elif value is not None:
            try:
                # MemoryReadValueType0 is dict-like (__contains__/__getitem__)
                # via attrs ``additional_properties`` but doesn't implement
                # ``.get()`` — so we can't use the SIM401 form here.
                inner = value["text"] if "text" in value else None  # noqa: SIM401
            except Exception:  # noqa: BLE001
                inner = None
            if isinstance(inner, str) and inner:
                yaml_body = inner
    if not yaml_body:
        return None

    try:
        data = yaml.safe_load(yaml_body) or {}
    except yaml.YAMLError as exc:
        _log.warning("remote manifest agents/%s: invalid YAML — %s", handle, exc)
        return None
    if not isinstance(data, dict):
        _log.warning(
            "remote manifest agents/%s: expected a YAML mapping, got %s",
            handle,
            type(data).__name__,
        )
        return None
    data.setdefault("handle", handle)
    try:
        return AgentManifest(**data)
    except ValidationError as exc:
        _log.warning("remote manifest agents/%s: schema validation failed — %s", handle, exc)
        return None


def _write_manifest(
    config: MyceliumConfig, room_name: str, manifest: AgentManifest, created_by: str
) -> None:
    """Upsert the manifest into the backend AND mirror it to the local filesystem.

    ``agent ls/show/invoke`` resolve manifests by reading the local filesystem, so
    the backend write alone isn't enough — we mirror via the same
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

    # Mirror locally so `agent ls/show/invoke` find the manifest without a
    # round-trip.
    room_dir = get_room_dir(room_name)
    version = 1
    if result and isinstance(result, list) and result:
        version = getattr(result[0], "version", 1) or 1
    try:
        write_memory(
            room_dir,
            manifest.memory_key,
            yaml_body,
            created_by=created_by,
            version=version,
            tags=["agent-manifest"],
        )
    except PermissionError:
        # Pre-check missed it (e.g., correct dir ownership but a stale
        # root-owned manifest file lurking from a previous run). Surface the
        # chown guidance the user expects.
        manifest_path = room_dir / f"{manifest.memory_key}.md"
        _check_writable_or_bail(manifest_path)
        raise


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
    # Permission pre-check BEFORE any side effects — bailing here means we
    # never allowlist or restart the gateway only to fail at the manifest
    # write. Closes #13 from the v1.1.0 tracking bug (#326).
    room_dir = get_room_dir(room_name)
    manifest_path = room_dir / f"{manifest.memory_key}.md"
    _check_writable_or_bail(manifest_path)
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
    _provision_channel_identity(manifest, config.slim.identity)
    _prompt_for_credential(config, manifest)


def _provision_channel_identity(manifest: AgentManifest, mode: str) -> None:
    """Provision the agent's SLIM channel identity for the active mode (#589).

    Registration is where ``@handle`` becomes a usable channel identity: under
    ``signerjwt`` this mints+registers the local keypair (``kid = @handle``); under
    ``spire`` it registers the SVID entry against the appliance SPIRE server. Under
    the ``psk`` default it is a silent no-op (off by default, #567) — the try-it
    path never sees identity machinery. A provisioning failure is a warning, not a
    hard error: the manifest is already written and the agent still works on the PSK.

    *mode* is the effective tier from ``config.slim.identity`` — the "one switch"
    (#588). The runtime resolves the mode from ``MYCELIUM_SLIM_IDENTITY`` (env-only),
    but a fresh CLI process doesn't inherit that env, so registration must read the
    config the user actually set, not just the environment.
    """
    from mycelium.slim import identity as slim_identity

    try:
        result = slim_identity.provision_channel_identity(manifest.handle, mode=mode)
    except slim_identity.SlimIdentityError as exc:
        console.print(f"[yellow]Could not provision channel identity: {exc}[/yellow]")
        return

    result_mode = result.get("mode")
    if result_mode == slim_identity.MODE_SIGNERJWT:
        console.print(
            f"[green]SLIM channel identity ready[/green] "
            f"[dim](signerjwt · kid {result['kid']})[/dim]"
        )
        console.print(f"[dim]Public JWK on the roster: {result['roster_path']}.[/dim]")
    elif result_mode == slim_identity.MODE_SPIRE:
        _register_spire_workload(manifest.handle, result)
    # psk: no per-agent identity — stay silent (off by default, #567).


def _register_spire_workload(handle: str, result: dict) -> None:
    """Register ``@handle``'s SVID entry against the appliance SPIRE server (#588).

    The clean end-state of the #589/#603 printed operator step: when the ``spire``
    compose profile is up, ``agent create`` registers the entry itself, so the user
    types zero SPIRE commands. If the server isn't reachable (spire selected but the
    stack isn't up, or a bespoke external SPIRE), we fall back to printing the
    operator step — the honest interim, never a silent failure.
    """
    from mycelium import spire_registry

    outcome = spire_registry.register_workload(handle)
    if outcome.ok:
        console.print(
            f"[green]SLIM channel identity[/green] [dim](spire · {outcome.spiffe_id})[/dim]"
        )
        console.print(f"[dim]SPIRE entry {outcome.message}.[/dim]")
        return

    console.print(
        f"[green]SLIM channel identity[/green] [dim](spire · {result['spiffe_id']})[/dim]"
    )
    console.print(f"[yellow]Could not auto-register the SVID entry: {outcome.message}[/yellow]")
    console.print(
        "[dim]Bring the appliance SPIRE up (mycelium up with slim.identity=spire), "
        "or register manually:[/dim]\n"
        f"[dim]  {result['operator_step']}[/dim]"
    )


def _revoke_spire_workload(handle: str, mode: str) -> None:
    """Revoke ``@handle``'s SPIRE SVID entry on ``agent rm`` (spire mode only).

    Silent unless *mode* is ``spire``: under psk/signerjwt there is no SPIRE entry,
    so this must not print or shell out. When spire is active but the server isn't
    reachable, the registry treats it as a no-op (nothing to revoke). *mode* is the
    effective tier from ``config.slim.identity`` (the "one switch", #588) — read
    from config, not env, since a fresh CLI process doesn't inherit
    ``MYCELIUM_SLIM_IDENTITY``.
    """
    from mycelium import spire_registry
    from mycelium.slim import identity as slim_identity

    if mode != slim_identity.MODE_SPIRE:
        return
    outcome = spire_registry.revoke_workload(handle)
    if outcome.ok:
        if outcome.entry_ids:
            console.print(f"[dim]Revoked SPIRE identity: {outcome.message}.[/dim]")
    else:
        console.print(f"[yellow]Could not revoke SPIRE identity: {outcome.message}[/yellow]")


def _prompt_for_credential(config: MyceliumConfig, manifest: AgentManifest) -> None:
    """Point at the credential step, but only where it means something.

    A hub with its gate off needs no credential, and saying otherwise on every
    ``agent create`` would make identity look mandatory when it is the opposite.
    So this speaks only once an issuer is configured — i.e. once this machine has
    somewhere to mint agent tokens from — and stays silent otherwise.
    """
    from mycelium import agent_credentials

    if not config.agent_auth.issuer:
        return
    if agent_credentials.resolve(config, manifest.handle) is not None:
        return
    console.print(
        f"\n[dim]@{manifest.handle} has no credential of its own yet — it would "
        f"authenticate as whoever runs it.[/dim]"
    )
    console.print(
        f"[dim]Give it one with: mycelium agent credential set {manifest.handle} "
        f"--secret-stdin[/dim]"
    )


#: CLI label per adapter for the wizard's cwd prompt. ``cwd`` is optional now
#: (it's the session's working dir / cursor's workspace root, not a launch
#: requirement). Single source of truth so the wizard prompt and ``--cwd`` flag
#: help stay in sync.
_CWD_PROMPT_BY_ADAPTER: dict[str, str] = {
    "claude_code": "Working directory for the agent's session (optional):",
    "cursor": "Workspace directory for the Cursor session (also drop site for .cursor/rules/mycelium.mdc + AGENTS.md):",
}


@doc_ref(
    usage="mycelium agent create <handle> --adapter <name> [--cwd <path>]",
    desc=(
        "Create a new, Mycelium-controlled agent in a room. "
        "<code>claude_code</code> and <code>cursor</code> agents are resident "
        "sessions the user keeps woken with <code>mycelium await --loop</code>."
    ),
    group="agent",
)
def _create_wizard(
    ctx: typer.Context,
    *,
    config: MyceliumConfig,
    room_opt: str | None,
    handle_flag: str,
) -> None:
    """Interactive `agent create` — prompt for the fields, then build +
    persist. Greenfield counterpart to `agent add`'s adopt picker.

    The per-adapter prompt (cwd) is a UI flow, not dispatch logic — the
    wizard simply asks for what the chosen adapter's manifest needs.
    """
    import os

    import questionary

    console.print(
        "\n[bold]Create a Mycelium agent[/bold]\n"
        "[dim]This will:[/dim]\n"
        "[dim]  · ask for the agent's handle, adapter, and details[/dim]\n"
        "[dim]  · register it as a Mycelium agent manifest in a room[/dim]\n"
        "[dim]  · cursor: drop .cursor/rules/mycelium.mdc + AGENTS.md into the "
        "workspace[/dim]\n"
    )

    handle = questionary.text("Agent handle (lowercase slug, e.g. release-agent):").ask()
    if not handle or not handle.strip():
        return
    handle = handle.strip()

    adapter = questionary.select(
        "Adapter that hosts this agent:",
        choices=sorted(AGENT_ADAPTERS),
        default="claude_code" if "claude_code" in AGENT_ADAPTERS else None,
    ).ask()
    if not adapter:
        return

    cwd: str | None = None
    prompt_label = _CWD_PROMPT_BY_ADAPTER.get(adapter)
    if prompt_label is not None:
        cwd = questionary.path(prompt_label, default=os.getcwd()).ask()
        if not cwd:
            return

    description = questionary.text("Description (what does this agent do?):").ask() or ""

    owner = (questionary.text("Owner (a users/<handle>, optional):").ask() or "").strip() or None
    team = (questionary.text("Team slug (optional):").ask() or "").strip() or None

    room_name = room_opt or _pick_room(config)
    if not room_name:
        return

    impl = get_adapter(adapter, cwd=cwd)
    try:
        manifest = impl.build_manifest(
            handle=handle,
            opts=AddOptions(room=room_name),
            description=description,
            allow_from=[],
            owner=owner,
            team=team,
        )
    except ValidationError as exc:
        typer.secho(f"Invalid agent manifest: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    _warn_unknown_principal(manifest)
    _persist_and_describe(
        impl=impl,
        manifest=manifest,
        config=config,
        room_name=room_name,
        handle_flag=handle_flag,
        verb="created",
    )


@app.command("create")
def agent_create(
    ctx: typer.Context,
    handle: str | None = typer.Argument(
        None,
        help=(
            "Agent handle (lowercase slug, e.g. 'release-agent'). "
            "Omit (in a TTY) for the interactive create form."
        ),
    ),
    adapter: str = typer.Option(
        "claude_code",
        "--adapter",
        help=f"Adapter that hosts this agent. Known: {', '.join(sorted(AGENT_ADAPTERS))}.",
    ),
    cwd: str | None = typer.Option(
        None,
        "--cwd",
        help=(
            "claude_code / cursor: optional working dir for the agent's session. "
            "For cursor it's also where .cursor/rules/mycelium.mdc + AGENTS.md "
            "(mycelium section) are dropped."
        ),
    ),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Room to register in (defaults to active room)."
    ),
    description: str = typer.Option(
        "", "--description", "-d", help="One-paragraph statement of what this agent does."
    ),
    allow_from: str | None = typer.Option(
        None,
        "--allow-from",
        help=(
            "Comma-separated sender handles allowed to invoke this agent, and — under "
            "an enabled auth gate — to act on its behalf (e.g. '@julia,@docs-agent')."
        ),
    ),
    owner: str | None = typer.Option(
        None,
        "--owner",
        help=(
            "User (a users/<handle>) this agent belongs to. Self-asserted, and the "
            "owner may act on the agent's behalf under an enabled auth gate."
        ),
    ),
    team: str | None = typer.Option(
        None, "--team", help="Team slug this agent is fielded by. Self-asserted."
    ),
    handle_flag: str = typer.Option(
        "cli-user", "--as", "-H", help="Your own handle (recorded as created_by)."
    ),
) -> None:
    """Create a new, Mycelium-controlled agent in a room.

    Examples:
        # claude_code (a resident session kept woken with `await --loop`)
        mycelium agent create release-agent --cwd ~/repos/mycelium

        # cursor (resident Cursor session; drops workspace rules)
        mycelium agent create design-agent --adapter cursor \\
            --cwd ~/repos/my-frontend \\
            --description "Owns the design system; pings @julia on ambiguity"
    """
    try:
        config = MyceliumConfig.load()

        # No handle in a terminal → interactive create form (mirrors the
        # `agent add` picker). Non-interactive with no handle → actionable
        # error so scripts/CI fail loud rather than hang on a prompt.
        if handle is None:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                typer.secho(
                    "mycelium agent create needs a handle when non-interactive.\n"
                    "  Interactive form: run it in a terminal.\n"
                    "  Scripted: mycelium agent create <handle> --adapter ... [--cwd ...]",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            _create_wizard(ctx, config=config, room_opt=room, handle_flag=handle_flag)
            return

        # `mycelium adapter add` accepts the kebab-case spelling
        # (``claude-code``); accept the same spelling here so users don't have
        # to remember which command uses which casing. The canonical id in
        # ``AGENT_ADAPTERS`` (and on the manifest) is the underscore form.
        adapter = adapter.replace("-", "_")
        if adapter not in AGENT_ADAPTERS:
            known = ", ".join(sorted(AGENT_ADAPTERS))
            typer.secho(f"Unknown adapter '{adapter}'. Known: {known}.", fg=typer.colors.RED)
            raise typer.Exit(1)

        allow_list: list[str] = []
        if allow_from:
            allow_list = [a.strip() for a in allow_from.split(",") if a.strip()]

        room_name = _resolve_room(config, room)

        impl = get_adapter(adapter, cwd=cwd)

        try:
            manifest = impl.build_manifest(
                handle=handle,
                opts=AddOptions(room=room_name),
                description=description,
                allow_from=allow_list,
                owner=owner,
                team=team,
            )
        except ValidationError as exc:
            typer.secho(f"Invalid agent manifest: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1) from exc

        _warn_unknown_principal(manifest)
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
    owner: str | None = typer.Option(
        None, "--owner", help="Filter to agents owned by this user handle ('my agents')."
    ),
    team: str | None = typer.Option(
        None, "--team", help="Filter to agents fielded by this team ('my team')."
    ),
) -> None:
    """List registered agents in a room."""
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        manifests = _room_manifests(room_name)
        if owner:
            wanted = owner.strip().lstrip("@").lower()
            manifests = [m for m in manifests if m.owner == wanted]
        if team:
            wanted = team.strip().lstrip("@").lower()
            manifests = [m for m in manifests if m.team == wanted]

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
        table.add_column("Owner", style="green")
        table.add_column("Team", style="green")
        table.add_column("Description", overflow="fold")
        for m in manifests:
            table.add_row(
                f"@{m.handle}",
                m.adapter,
                f"@{m.owner}" if m.owner else "[dim]—[/dim]",
                m.team or "[dim]—[/dim]",
                (m.description or "")[:60],
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
        if manifest.owner:
            console.print(f"  owner: @{manifest.owner}")
        if manifest.team:
            console.print(f"  team: {manifest.team}")
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

    Typing comfort over `mycelium room send "@handle ..."`. The message lands in
    the room's transcript; a resident agent (one running `mycelium await --loop`)
    picks it up on its next await. If nothing is resident for the handle, the
    message waits on the durable cursor until a runtime comes up.

    Examples:
        mycelium agent invoke release-agent "pull latest, new release"
        mycelium agent invoke docs-agent "regen the cli reference"
    """
    try:
        config = MyceliumConfig.load()
        room_name = _resolve_room(config, room)

        from mycelium_backend_client.api.messages import (
            send_message_api_rooms_room_name_messages_post as send_api,
        )
        from mycelium_backend_client.models import MessageCreate

        with _typed_client(config) as client:
            manifest = _load_manifest(room_name, handle)
            if manifest is None:
                # Cross-host case: the agent may be registered on a different
                # machine that hasn't mirrored its manifest down to ours yet.
                # Fall through to the backend (source of truth) before failing.
                manifest = _load_manifest_remote(client, room_name, handle)
            if manifest is None:
                console.print(
                    f"[red]Not found:[/red] no agent named '{handle}' in room '{room_name}'.\n"
                    f"  Create one with: mycelium agent create {handle} --cwd <path> --room {room_name}"
                )
                raise typer.Exit(1)

            sender_handle = handle_flag or config.get_current_identity()
            content = f"@{manifest.handle} {prompt}"

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
        # Report residence honestly: durability (message recorded) is not liveness
        # (message handled). Tell the user whether a runtime is actually awake for
        # this handle right now, or whether the message waits on the cursor.
        if _is_resident(config, room_name, manifest.handle):
            console.print(
                f"\n[dim]@{manifest.handle} is resident — it'll pick this up on its "
                f"next await.[/dim]"
            )
        else:
            console.print(
                f"\n[dim]@{manifest.handle} is not resident — queued on the transcript "
                f"until a runtime awaits (start one with `mycelium await --loop "
                f"--room {room_name} --handle {manifest.handle}`).[/dim]"
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
        "<code>--full</code> also tears down the underlying runtime "
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
        help=("Destructive: also tear down the underlying runtime."),
    ),
    force: bool = typer.Option(False, "--force", "-f", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Unregister an agent.

    **Default (safe):** deletes the manifest. Notes/logs are preserved so the
    agent can be re-registered later.

    **--full (destructive):** additionally tears down the underlying runtime.
    Always prompts unless -y/--force.
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

        # 3. Revoke the SPIRE SVID entry (spire mode only; #588/#590). No-op under
        # psk/signerjwt, or when the appliance SPIRE server isn't up — there's
        # nothing to revoke. Best-effort: a failure is a warning, not a hard error.
        _revoke_spire_workload(handle, config.slim.identity)

        verb = "Destroyed" if will_destroy else "Unregistered"
        console.print(f"[green]{verb}:[/green] @{handle} from {room_name}")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# ── credential ───────────────────────────────────────────────────────────────
#
# An agent's own credential, so its writes carry *its* identity rather than
# whoever happens to be logged in on the machine it runs on. Client-side only:
# nothing here is stored in the room, because a manifest is shared state and a
# client secret is not. See `mycelium.agent_credentials`.

credential_app = typer.Typer(
    help=(
        "Manage an agent's own credential — the service-account client it "
        "authenticates to a gated hub as. Not needed while the hub's gate is off."
    ),
    no_args_is_help=True,
)
app.add_typer(credential_app, name="credential")


@doc_ref(
    usage="mycelium agent credential set <handle> [--client-id ID] [--secret-stdin] [--issuer URL]",
    desc=(
        "Give an agent its own service-account credential, stored 0600 outside "
        "<code>config.toml</code>. Only meaningful once a hub enables auth."
    ),
    group="agent",
)
@credential_app.command("set")
def credential_set(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle the credential belongs to"),
    client_id: str | None = typer.Option(
        None, "--client-id", help="OAuth client id (default: the handle itself)."
    ),
    secret: str | None = typer.Option(
        None, "--secret", help="Client secret. Prefer --secret-stdin; this lands in shell history."
    ),
    secret_stdin: bool = typer.Option(
        False, "--secret-stdin", help="Read the client secret from stdin."
    ),
    issuer: str | None = typer.Option(
        None, "--issuer", help="Issuer for this agent (default: agent_auth.issuer)."
    ),
    scopes: str | None = typer.Option(None, "--scopes", help="Scopes to request for this agent."),
    audience: str | None = typer.Option(
        None, "--audience", help="Audience to request; should match the hub's auth.audience."
    ),
) -> None:
    """Record the credential an agent presents to a gated hub.

    The token minted from it carries the agent's handle as its `sub`, which is
    what the hub binds the agent's writes to. Each agent gets its own client, so
    revoking one agent's credential leaves every other agent working.

    Examples:
        mycelium agent credential set release-agent --secret-stdin < secret.txt
        mycelium agent credential set release-agent --client-id svc-release --secret-stdin
    """
    from mycelium import agent_credentials

    try:
        config = MyceliumConfig.load()
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        if secret_stdin:
            secret = sys.stdin.read().strip() or None
        elif secret is None and sys.stdin.isatty():
            secret = (
                typer.prompt(
                    "Client secret (blank if the issuer needs none)", default="", hide_input=True
                )
                or None
            )

        path = agent_credentials.save_credential(
            handle,
            client_id=client_id,
            client_secret=secret,
            issuer=issuer,
            scopes=scopes,
            audience=audience,
        )
        resolved = agent_credentials.describe(config, handle)

        if json_output:
            typer.echo(json_module.dumps({"stored": str(path), **resolved}, indent=2))
            return

        console.print(
            f"[green]Credential stored[/green] for [cyan]@{resolved['handle']}[/cyan] "
            f"[dim](client_id: {resolved['client_id']})[/dim]"
        )
        console.print(f"[dim]Saved to {path} (mode 0600).[/dim]")
        if not resolved.get("issuer"):
            console.print(
                "\n[yellow]No issuer resolved[/yellow] — the credential can't be minted yet."
            )
            console.print("[dim]Set one with: mycelium config set agent_auth.issuer <url>[/dim]")
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium agent credential show <handle>",
    desc="Show which credential an agent resolves to. Never prints the secret.",
    group="agent",
)
@credential_app.command("show")
def credential_show(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
) -> None:
    """Report an agent's resolved credential and the state of its cached token."""
    from mycelium import agent_credentials

    try:
        config = MyceliumConfig.load()
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        resolved = agent_credentials.describe(config, handle)

        if json_output:
            typer.echo(json_module.dumps(resolved, indent=2))
            return

        if not resolved.get("configured"):
            console.print(
                f"[dim]@{resolved['handle']} has no credential — it sends no token "
                f"(which is all an ungated hub needs).[/dim]"
            )
            return

        table = Table(show_header=False, box=None)
        table.add_row("handle", f"@{resolved['handle']}")
        table.add_row("client_id", resolved["client_id"] or "—")
        table.add_row("issuer", resolved["issuer"] or "[yellow]none[/yellow]")
        table.add_row("audience", resolved["audience"] or "—")
        table.add_row("scopes", resolved["scopes"] or "—")
        table.add_row("secret", "set" if resolved["has_secret"] else "—")
        if resolved["static_token"]:
            table.add_row("token", f"supplied via {agent_credentials.STATIC_TOKEN_ENV}")
        cached = resolved.get("cached_token")
        if cached:
            state = "expired" if cached["expired"] else f"{int(cached['expires_in_s'] or 0)}s left"
            table.add_row("cached token", state)
        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium agent credential ls",
    desc="List the agents on this machine that have their own credential.",
    group="agent",
)
@credential_app.command("ls")
def credential_ls(ctx: typer.Context) -> None:
    """List stored per-agent credentials (never their secrets)."""
    from mycelium import agent_credentials

    try:
        stored = agent_credentials.list_credentials()
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        if json_output:
            typer.echo(
                json_module.dumps([c.redacted() for c in stored.values()], indent=2, sort_keys=True)
            )
            return

        if not stored:
            console.print("[dim]No agent credentials on this machine.[/dim]")
            return

        table = Table(title="Agent credentials")
        table.add_column("handle", style="cyan")
        table.add_column("client_id")
        table.add_column("issuer")
        table.add_column("secret")
        for cred in sorted(stored.values(), key=lambda c: c.handle):
            table.add_row(
                f"@{cred.handle}",
                cred.client_id,
                cred.issuer or "[dim]agent_auth.issuer[/dim]",
                "set" if cred.client_secret else "—",
            )
        console.print(table)
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium agent credential rm <handle>",
    desc="Forget an agent's credential on this machine.",
    group="agent",
)
@credential_app.command("rm")
def credential_rm(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle"),
) -> None:
    """Drop an agent's stored credential and any token minted from it.

    This is local forgetting, not revocation: the client still exists at the
    issuer until it is revoked there.
    """
    from mycelium import agent_credentials

    try:
        existed = agent_credentials.remove_credential(handle)
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            typer.echo(json_module.dumps({"removed": existed}))
            return
        if existed:
            console.print(f"[green]Removed[/green] the credential for @{handle}.")
            console.print(
                "[dim]Revoke the client at the issuer too — this only forgot it here.[/dim]"
            )
        else:
            console.print(f"[dim]@{handle} had no credential here — nothing to do.[/dim]")
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium agent credential slim-key <handle>",
    desc=(
        "Mint an agent's SignerJwt SLIM channel identity — a local ES256 keypair "
        "(0600) whose public JWK is registered on the room roster. The floor for "
        "<code>slim.identity = signerjwt</code> (#476); the PSK default needs none."
    ),
    group="agent",
)
@credential_app.command("slim-key")
def credential_slim_key(
    ctx: typer.Context,
    handle: str = typer.Argument(..., help="Agent handle the signing key belongs to"),
) -> None:
    """Generate + register the agent's SignerJwt-floor SLIM channel identity.

    The SignerJwt analogue of ``credential set``: the private ES256 key stays
    local (0600), and only the **public** JWK is registered — keyed by
    ``kid = @handle`` — into the roster the moderator assembles so peers can
    verify this agent's self-signed tokens. Idempotent: an existing key is reused.
    Only meaningful when the channel identity tier is ``signerjwt``; the PSK
    default (off by default, #567) uses no per-agent key. Revoke by dropping the
    roster JWK (per-agent, no room-wide rotation).
    """
    from mycelium.slim import identity as slim_identity

    try:
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        key_path, jwk = slim_identity.ensure_agent_keypair(handle)
        roster_path = slim_identity.public_jwk_path(handle)
        mode = slim_identity.resolve_identity_mode()

        if json_output:
            typer.echo(
                json_module.dumps(
                    {
                        "handle": handle,
                        "key": str(key_path),
                        "jwk": str(roster_path),
                        "kid": jwk["kid"],
                    },
                    indent=2,
                )
            )
            return

        console.print(
            f"[green]SLIM signing key ready[/green] for [cyan]@{handle}[/cyan] "
            f"[dim](kid: {jwk['kid']})[/dim]"
        )
        console.print(f"[dim]Private key: {key_path} (mode 0600).[/dim]")
        console.print(f"[dim]Public JWK registered on the roster: {roster_path}.[/dim]")
        if mode != slim_identity.MODE_SIGNERJWT:
            console.print(
                "\n[yellow]Channel identity is still 'psk'[/yellow] — this key is unused "
                "until you set [cyan]slim.identity = signerjwt[/cyan] "
                "(or MYCELIUM_SLIM_IDENTITY=signerjwt)."
            )
    except typer.Exit:
        raise
    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None


# Re-export for completeness — doctor and other commands reuse these.
__all__ = [
    "_load_manifest",
    "_load_manifest_remote",
    "app",
]
