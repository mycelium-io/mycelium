# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium pattern``: load a multi-agent design pattern as a room, ready to run.

A scenario is a small room: a cast, some context, a task and the flow that sets
them working. The hub owns what a scenario is and what loading one writes
(``POST /api/patterns/...``), so this is a thin caller.

- ``pattern ls`` / ``pattern use <name>`` use the pack the hub's operator
  provides (``PATTERNS_DIR`` on the hub). The hub never fetches a pack a caller
  names, so this is also the only form a public hub offers.
- ``--from`` names a pack of your own, a git URL or a folder. A URL is cloned
  shallowly into ``~/.mycelium/patterns/`` with your own git credentials, so a
  private pack needs nothing stored here, and the scenario is sent to the hub
  in the request. A hub can turn that off (``PATTERNS_ALLOW_INLINE``).

A scenario loads **paused**. The summon that starts it is printed, or posted
when ``--run`` is given. If a step fails the hub removes the room.
"""

from __future__ import annotations

import hashlib
import json as json_module
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

from mycelium import identity
from mycelium.cli_options import acts_as, emits_json
from mycelium.client import hub_client, hub_error_detail
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Load a multi-agent design pattern as a room, ready to run.", no_args_is_help=True
)
console = Console()

CONDUCTOR = "conductor"
CLONE_TIMEOUT_S = 120

SOURCE_HELP = (
    "A pattern pack of your own: a git URL (cloned with your git credentials) or a folder. "
    "Without it, the pack the hub provides."
)


class PatternError(Exception):
    """A pack or scenario that cannot be found or read, or a hub that refused it."""


# ── a pack of your own ───────────────────────────────────────────────────────


@dataclass
class Pack:
    """A folder of scenarios, wherever it came from."""

    root: Path
    source: str

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"

    def names(self) -> list[str]:
        return sorted(p.parent.name for p in self.scenarios_dir.glob("*/scenario.yaml"))

    def read(self, name: str) -> tuple[dict[str, Any], str | None]:
        """A scenario as parsed YAML, and its flow's text when it brings one.

        Not checked here: the hub checks a scenario against its own models and
        flows, and says what is wrong.
        """
        folder = self.scenarios_dir / name
        path = folder / "scenario.yaml"
        if not path.is_file():
            known = ", ".join(self.names()) or "none"
            raise PatternError(f"no scenario named {name!r} in {self.source}. Known: {known}.")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PatternError(f"{name}: scenario.yaml cannot be read: {exc}") from exc
        if not isinstance(data, dict):
            raise PatternError(f"{name}: scenario.yaml is not a mapping")
        flow_file = data.get("flow_file")
        if flow_file is None:
            return data, None
        flow_path = (folder / str(flow_file)).resolve()
        if folder.resolve() not in flow_path.parents or not flow_path.is_file():
            raise PatternError(f"{name}: flow_file {flow_file!r} is not a file in the folder")
        return data, flow_path.read_text(encoding="utf-8")


def _is_url(source: str) -> bool:
    return bool(re.match(r"^(https?://|git@|ssh://|git://)", source))


def cache_dir() -> Path:
    return MyceliumConfig.get_global_config_dir() / "patterns"


def fetch_pack(source: str) -> Pack:
    """The pack at ``source``: a folder used as it is, or a git URL cloned (or
    brought up to date) under ``~/.mycelium/patterns/``."""
    if not _is_url(source):
        root = Path(source).expanduser()
        if not root.is_dir():
            raise PatternError(f"{source} is not a folder or a git URL.")
        return Pack(root=root, source=source)

    if shutil.which("git") is None:
        raise PatternError("git is needed to fetch a pattern pack from a URL.")
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[-40:]
    dest = cache_dir() / f"{slug}-{hashlib.sha256(source.encode()).hexdigest()[:8]}"
    if (dest / ".git").is_dir():
        _git(["-C", str(dest), "fetch", "--depth", "1", "origin"], source)
        _git(["-C", str(dest), "reset", "--hard", "FETCH_HEAD"], source)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(dest, ignore_errors=True)
        _git(["clone", "--depth", "1", source, str(dest)], source)
    return Pack(root=dest, source=source)


def _git(args: list[str], source: str) -> None:
    try:
        proc = subprocess.run(  # noqa: S603 - arguments are code-built
            ["git", *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PatternError(f"git timed out fetching {source}.") from exc
    if proc.returncode != 0:
        raise PatternError(
            f"could not fetch {source}: {proc.stderr.strip() or 'git failed'}\n"
            "For a private pack, make sure git can reach it with your own credentials."
        )


# ── the hub ──────────────────────────────────────────────────────────────────


def _checked(resp: httpx.Response, what: str) -> Any:
    """The response's JSON, or the hub's reason it refused."""
    if resp.status_code >= 400:
        detail = hub_error_detail(resp.content) or resp.text.strip() or f"HTTP {resp.status_code}"
        raise PatternError(f"could not {what}: {detail}")
    return resp.json()


def hub_patterns(client: httpx.Client) -> dict[str, Any]:
    return _checked(client.get("/api/patterns"), "list the hub's patterns")


def load_on_hub(
    client: httpx.Client,
    name: str,
    options: dict[str, Any],
    pack: Pack | None,
) -> dict[str, Any]:
    """Ask the hub to load ``name``: from its own pack, or with a scenario of yours."""
    if pack is None:
        return _checked(client.post(f"/api/patterns/{name}/load", json=options), f"load {name}")
    scenario, flow = pack.read(name)
    body = {**options, "scenario": scenario, "flow": flow}
    return _checked(client.post("/api/patterns/load", json=body), f"load {name}")


# ── commands ─────────────────────────────────────────────────────────────────


@doc_ref(
    usage="mycelium pattern ls [--from <url|folder>]",
    desc="List the design patterns the hub offers, or those in a pack of your own.",
    group="room",
)
@app.command("ls")
@emits_json()
def pattern_ls(
    ctx: typer.Context,
    source: str | None = typer.Option(None, "--from", help=SOURCE_HELP),
) -> None:
    """List the patterns you can load."""
    try:
        rows: list[dict[str, Any]]
        skipped: dict[str, str] = {}
        where = "the hub"
        if source:
            pack = fetch_pack(source)
            where = source
            rows = []
            for name in pack.names():
                try:
                    data, _ = pack.read(name)
                except PatternError as exc:
                    skipped[name] = str(exc)
                    continue
                summon = data.get("summon") or {}
                rows.append(
                    {
                        "pattern": name,
                        "summary": data.get("summary", ""),
                        "flow": summon.get("flow") if isinstance(summon, dict) else None,
                        "members": [
                            {"handle": m.get("handle")}
                            for m in data.get("members") or []
                            if isinstance(m, dict)
                        ],
                    }
                )
        else:
            with hub_client() as client:
                listed = hub_patterns(client)
            rows, skipped = listed["patterns"], listed.get("skipped", {})

        if ctx.obj and ctx.obj.get("json"):
            typer.echo(json_module.dumps({"patterns": rows, "skipped": skipped}, indent=2))
            return
        if not rows and not skipped:
            console.print(f"[dim]No patterns on {where}.[/dim]")
            return
        table = Table(title=f"patterns on {where}", show_lines=False)
        table.add_column("pattern", style="cyan", no_wrap=True)
        table.add_column("flow")
        table.add_column("cast")
        table.add_column("summary")
        for row in rows:
            cast = ", ".join(str(m.get("handle")) for m in row.get("members") or [])
            table.add_row(row["pattern"], row.get("flow") or "-", cast, row.get("summary", ""))
        console.print(table)
        for name, why in skipped.items():
            console.print(f"[yellow]skipped {name}:[/yellow] {why}")
    except PatternError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium pattern use <pattern> [--from <url|folder>] [--room <name>] [--run]",
    desc="Load a design pattern as a new room: its members, context, task and flow. It loads paused; <code>--run</code> starts it.",
    group="room",
)
@app.command("use")
@acts_as("handle_flag")
def pattern_use(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="The pattern to load (see 'mycelium pattern ls')."),
    source: str | None = typer.Option(None, "--from", help=SOURCE_HELP),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Name for the new room (defaults to the pattern's name)."
    ),
    run: bool = typer.Option(False, "--run", help="Start the flow once the room is loaded."),
    private: bool = typer.Option(False, "--private", help="Make the room private to you."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be created and write nothing."
    ),
    handle_flag: str | None = None,
) -> None:
    """Load a pattern as a new room, paused.

    Example:
        mycelium pattern use approval-gate-agent
        mycelium pattern use approval-gate-agent --from ./my-patterns --run
    """
    try:
        config = MyceliumConfig.load()
        me = identity.resolve_actor(config, override=handle_flag)
        pack = fetch_pack(source) if source else None
        options: dict[str, Any] = {
            "room": room,
            "private": private,
            "run": run,
            "dry_run": dry_run,
            "created_by": me,
        }
        with hub_client(config, handle=me) as client:
            loaded = load_on_hub(client, pattern, options, pack)

        if ctx.obj and ctx.obj.get("json"):
            typer.echo(json_module.dumps(loaded, indent=2))
            return
        _print_loaded(loaded, me)
    except PatternError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


def _print_loaded(loaded: dict[str, Any], me: str) -> None:
    room = loaded["room"]
    dry = bool(loaded.get("dry_run"))
    console.print(
        f"[bold]{'Would create' if dry else 'Loaded'}[/bold] room [cyan]{room}[/cyan]: "
        f"{loaded.get('title', '')}"
    )
    for handle in loaded.get("members", []):
        console.print(f"  [dim]engine[/dim] @{handle}")
    console.print(f"  [dim]you[/dim]    @{me}")
    console.print(f"  [dim]{len(loaded.get('memories', []))} memories written[/dim]")
    summon = loaded.get("summon")
    if dry:
        return
    if not summon:
        console.print("\n[dim]No flow to run: the room is ready to work in.[/dim]")
    elif loaded.get("ran"):
        console.print(f"\n[green]Started[/green] on {loaded.get('key')}.")
    else:
        ask = str(summon).removeprefix(f"@{CONDUCTOR} ")
        console.print("\nIt is [bold]paused[/bold]. Start it with:")
        # One unbroken line: it is meant to be copied.
        console.print(
            f'  mycelium board coordinate {loaded.get("key")} {CONDUCTOR} "{ask}" --room {room}',
            soft_wrap=True,
            markup=False,
        )
    console.print(f"\nOpen it: mycelium watch --room {room}")
