# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium pattern``: load a multi-agent design pattern as a room, ready to run.

A pattern pack is a repository of scenarios
(``scenarios/<pattern>/scenario.yaml``): a cast, some context, a task and the flow
that sets them working. ``--from`` names the repository, a git URL or a folder; a URL is cloned shallowly into ``~/.mycelium/patterns/`` with the
caller's own git credentials, so a private pack needs nothing stored here.

Loading is a sequence of calls the hub already answers (the room, its engines
and members' notes, the context and the flow as memories, the task) and then
stops: the scenario is **paused**. The summon that starts it is printed, or
posted when ``--run`` is given. If a step fails the room is removed, so a
half-loaded scenario is never left behind.
"""

from __future__ import annotations

import hashlib
import json as json_module
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import typer
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from rich.console import Console
from rich.table import Table

from mycelium import identity
from mycelium.client import hub_client
from mycelium.commands.swarm import CONDUCTOR, SwarmError, _check
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.error_handler import print_error

app = typer.Typer(
    help="Load a multi-agent design pattern as a room, ready to run.", no_args_is_help=True
)
console = Console()

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: The flows the hub ships; a scenario naming any other brings its own.
BUILTIN_FLOWS = frozenset(
    {"round-robin", "fan-out", "swarm", "review", "gated", "concord", "accord"}
)

#: The seat the person loading a scenario takes.
HUMAN = "human"

#: What a member can be that the hub runs; ``human`` is the loader.
Kind = Literal["persona", "worker", "aligner", "synthesizer", "hello", "human"]

#: Kinds a flow can put a question to.
ASKABLE = frozenset({"persona", "worker", "human"})

CLONE_TIMEOUT_S = 120


class PatternError(Exception):
    """A scenario that cannot be found, read or loaded, with what to do about it."""


# ── the scenario ─────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Context(_Strict):
    key: str
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _under_context(self) -> Context:
        if not self.key.startswith("context/") or not SLUG.match(self.key.removeprefix("context/")):
            msg = f"context key {self.key!r} must be context/<slug>"
            raise ValueError(msg)
        return self


class Member(_Strict):
    handle: str
    kind: Kind
    description: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _shape(self) -> Member:
        if not SLUG.match(self.handle) or self.handle == CONDUCTOR:
            msg = f"handle {self.handle!r} must be a lowercase slug and not {CONDUCTOR!r}"
            raise ValueError(msg)
        if self.kind in ("persona", "worker") and not self.notes.strip():
            msg = f"{self.kind} {self.handle!r} needs notes: they are its character"
            raise ValueError(msg)
        return self


class Task(_Strict):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""


class Summon(_Strict):
    flow: str
    members: list[str] = Field(min_length=1)
    ask: str = Field(min_length=1)


class Room(_Strict):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=500)


class Scenario(_Strict):
    pattern: str
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=300)
    room: Room
    context: list[Context] = Field(default_factory=list)
    members: list[Member] = Field(min_length=1)
    task: Task
    summon: Summon | None = None
    flow_file: str | None = None

    #: The flow's YAML, read from ``flow_file`` when a scenario has one.
    flow_body: str | None = Field(None, exclude=True)

    def check(self) -> list[str]:
        """What is wrong with the scenario as data. The hub's own flow check
        runs in the pack's CI and, once loaded, against the room's flow list."""
        errors: list[str] = []
        handles = [m.handle for m in self.members]
        if len(set(handles)) != len(handles):
            errors.append("member handles must be distinct")
        if sum(m.kind == HUMAN for m in self.members) > 1:
            errors.append("at most one human seat: the person who loads it")
        if len({c.key for c in self.context}) != len(self.context):
            errors.append("context keys must be distinct")
        if self.flow_file and self.summon is None:
            errors.append("flow_file is set but there is no summon to run it")
        if self.summon is None:
            return errors
        if not self.flow_file and self.summon.flow not in BUILTIN_FLOWS:
            errors.append(
                f"summon.flow {self.summon.flow!r} is not built in "
                f"({', '.join(sorted(BUILTIN_FLOWS))}) and no flow_file is given"
            )
        by_handle = {m.handle: m for m in self.members}
        cast = self.summon.members
        if len(set(cast)) != len(cast):
            errors.append("summon members must be distinct")
        for handle in cast:
            member = by_handle.get(handle)
            if member is None:
                errors.append(f"summon names {handle!r}, which the scenario does not cast")
            elif member.kind not in ASKABLE:
                errors.append(f"{handle!r} is a {member.kind}, which a flow cannot ask")
        return errors


# ── the pack ─────────────────────────────────────────────────────────────────


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

    def load(self, name: str) -> Scenario:
        folder = self.scenarios_dir / name
        path = folder / "scenario.yaml"
        if not path.is_file():
            known = ", ".join(self.names()) or "none"
            raise PatternError(f"no scenario named {name!r} in {self.source}. Known: {known}.")
        try:
            scenario = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError, OSError) as exc:
            raise PatternError(f"{name}: scenario.yaml is not valid: {exc}") from exc
        if scenario.pattern != name:
            raise PatternError(f"{name}: pattern {scenario.pattern!r} must match its folder")
        if scenario.flow_file:
            flow_path = (folder / scenario.flow_file).resolve()
            if folder.resolve() not in flow_path.parents or not flow_path.is_file():
                raise PatternError(f"{name}: flow_file {scenario.flow_file!r} is not in the folder")
            scenario.flow_body = flow_path.read_text(encoding="utf-8")
        problems = scenario.check()
        if problems:
            raise PatternError(f"{name}: " + "; ".join(problems))
        return scenario


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


# ── the plan ─────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    """What loading a scenario does, worked out before the hub is touched."""

    room: str
    me: str
    scenario: Scenario
    #: ``(handle, kind, description)`` for every engine to register.
    engines: list[tuple[str, str, str]]
    #: Memory items, in the order they are written.
    memories: list[dict[str, Any]]
    #: The summon text, with the person's own handle in their seat.
    summon: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "room": self.room,
            "title": self.scenario.room.title,
            "engines": [{"handle": h, "kind": k} for h, k, _ in self.engines],
            "memories": [m["key"] for m in self.memories],
            "task": self.scenario.task.title,
            "summon": self.summon,
        }


def build_plan(scenario: Scenario, room: str, me: str) -> Plan:
    """The calls loading ``scenario`` into ``room`` as ``me`` will make."""
    seat = {m.handle: (me if m.kind == HUMAN else m.handle) for m in scenario.members}
    engines: list[tuple[str, str, str]] = []
    if scenario.summon is not None:
        engines.append((CONDUCTOR, "conductor", f"Runs the {scenario.summon.flow} flow."))
    engines += [(m.handle, m.kind, m.description) for m in scenario.members if m.kind != HUMAN]

    memories: list[dict[str, Any]] = [
        {"key": c.key, "value": c.text.strip(), "created_by": me} for c in scenario.context
    ]
    memories += [
        {
            "key": f"agents/{m.handle}/notes",
            "value": m.notes.strip(),
            "created_by": me,
            "embed": False,
        }
        for m in scenario.members
        if m.notes.strip()
    ]
    summon = None
    if scenario.summon is not None:
        if scenario.flow_body:
            memories.append(
                {
                    "key": f"protocols/{scenario.summon.flow}",
                    "value": scenario.flow_body,
                    "created_by": me,
                    "embed": False,
                }
            )
        names = " ".join(f"@{seat[h]}" for h in scenario.summon.members)
        summon = f"@{CONDUCTOR} {scenario.summon.flow} {names}: {scenario.summon.ask}"
    return Plan(
        room=room, me=me, scenario=scenario, engines=engines, memories=memories, summon=summon
    )


def free_room_name(client: httpx.Client, wanted: str, *, exact: bool) -> str:
    """``wanted`` if no room has it. Creating a room that exists quietly reuses
    it, so a taken name is refused when asked for and counted past otherwise."""
    taken = _room_exists(client, wanted)
    if not taken:
        return wanted
    if exact:
        raise PatternError(
            f"a room named {wanted!r} already exists. Pick another name with --room."
        )
    for n in range(2, 100):
        candidate = f"{wanted}-{n}"
        if not _room_exists(client, candidate):
            return candidate
    raise PatternError(f"no free room name starting {wanted!r}.")


def _room_exists(client: httpx.Client, name: str) -> bool:
    resp = client.get(f"/api/rooms/{name}")
    if resp.status_code == 404:
        return False
    _check(resp, f"look for room {name}")
    return True


# ── the load ─────────────────────────────────────────────────────────────────


def load(
    client: httpx.Client, plan: Plan, *, private: bool = False, run: bool = False
) -> tuple[str, str]:
    """Make the room from ``plan``; ``(task key, task thread)``. A failure takes
    the room away again and says which step it was."""
    scenario = plan.scenario
    created = False
    try:
        body: dict[str, Any] = {
            "name": plan.room,
            "title": scenario.room.title,
            "description": scenario.room.description or None,
            "is_public": not private,
            "owner": plan.me,
        }
        _check(client.post("/api/rooms", json=body), "create the room")
        created = True

        for handle, kind, description in plan.engines:
            engine = {
                "handle": handle,
                "kind": kind,
                "description": description,
                "created_by": plan.me,
            }
            resp = client.post(f"/api/rooms/{plan.room}/engines", json=engine)
            if resp.status_code == 422 and "engine kind" in resp.text:
                raise SwarmError(
                    f"this hub doesn't run {kind} engines yet. Upgrade it (mycelium upgrade)."
                )
            _check(resp, f"register @{handle}")

        _check(
            client.post(f"/api/rooms/{plan.room}/memory", json={"items": plan.memories}),
            "write the context and the members' notes",
        )
        if scenario.summon is not None:
            _check_flow_listed(client, plan.room, scenario.summon.flow, scenario.flow_body)

        task = _check(
            client.post(
                f"/api/rooms/{plan.room}/tasks",
                json={"title": scenario.task.title, "handle": plan.me},
            ),
            "file the task",
        ).json()
        key, episode = str(task["key"]), str(task.get("episode") or "")
        if scenario.task.body.strip():
            item = {
                "key": key,
                "value": f"{scenario.task.title}\n\n{scenario.task.body.strip()}",
                "created_by": plan.me,
            }
            _check(
                client.post(f"/api/rooms/{plan.room}/memory", json={"items": [item]}),
                "write the task",
            )

        if run and plan.summon is not None:
            message = {
                "sender_handle": plan.me,
                "message_type": "broadcast",
                "content": plan.summon,
                "episode": episode,
            }
            _check(client.post(f"/api/rooms/{plan.room}/messages", json=message), "start the flow")
        return key, episode
    except (SwarmError, httpx.HTTPError, KeyError):
        if created:
            client.delete(f"/api/rooms/{plan.room}")
        raise


def _check_flow_listed(client: httpx.Client, room: str, flow: str, body: str | None) -> None:
    """The hub does not check a flow when it is saved: a bad one is left out of
    the room's flows. Look for it, so a broken pack fails here and not mid-run."""
    flows = _check(client.get(f"/api/rooms/{room}/protocols"), "list the room's flows").json()
    found = {f["name"]: f.get("source") for f in flows}
    if flow not in found:
        raise SwarmError(
            f"the hub did not accept the flow {flow!r}"
            + (" (its protocol.yaml does not parse)" if body else "")
        )
    if body and found[flow] != "room":
        raise SwarmError(f"the hub kept its built-in {flow!r} instead of the pack's flow")


# ── commands ─────────────────────────────────────────────────────────────────


SOURCE_HELP = "Pattern pack: a git URL (cloned with your own git credentials) or a folder."


@doc_ref(
    usage="mycelium pattern ls --from <url|folder>",
    desc="List the scenarios in a pattern pack: a git URL or a folder.",
    group="room",
)
@app.command("ls")
def pattern_ls(
    ctx: typer.Context,
    source: str = typer.Option(..., "--from", help=SOURCE_HELP),
) -> None:
    """List the scenarios in a pattern pack."""
    try:
        pack = fetch_pack(source)
        loaded: list[Scenario] = []
        failed: list[str] = []
        for name in pack.names():
            try:
                loaded.append(pack.load(name))
            except PatternError as exc:
                failed.append(str(exc))
        if ctx.obj and ctx.obj.get("json"):
            console.print(
                json_module.dumps(
                    [
                        {
                            "pattern": s.pattern,
                            "title": s.title,
                            "summary": s.summary,
                            "flow": s.summon.flow if s.summon else None,
                            "members": [{"handle": m.handle, "kind": m.kind} for m in s.members],
                        }
                        for s in loaded
                    ],
                    indent=2,
                )
            )
            return
        if not loaded and not failed:
            console.print(f"[dim]No scenarios in {source}.[/dim]")
            return
        table = Table(title=f"patterns in {source}", show_lines=False)
        table.add_column("pattern", style="cyan")
        table.add_column("flow")
        table.add_column("cast")
        table.add_column("summary")
        for s in loaded:
            cast = ", ".join(f"{m.handle}" for m in s.members)
            table.add_row(s.pattern, s.summon.flow if s.summon else "-", cast, s.summary)
        console.print(table)
        for problem in failed:
            console.print(f"[yellow]skipped:[/yellow] {problem}")
    except PatternError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


@doc_ref(
    usage="mycelium pattern use <pattern> --from <url|folder> [--room <name>] [--run]",
    desc="Load a pattern as a new room: its members, context, task and flow. It loads paused; <code>--run</code> starts it.",
    group="room",
)
@app.command("use")
def pattern_use(
    ctx: typer.Context,
    pattern: str = typer.Argument(..., help="The pattern to load (see 'mycelium pattern ls')."),
    source: str = typer.Option(..., "--from", help=SOURCE_HELP),
    room: str | None = typer.Option(
        None, "--room", "-r", help="Name for the new room (defaults to the pattern's name)."
    ),
    run: bool = typer.Option(False, "--run", help="Start the flow once the room is loaded."),
    private: bool = typer.Option(False, "--private", help="Make the room private to you."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be created and touch nothing."
    ),
    handle_flag: str | None = typer.Option(
        None, "--as", "--handle", "-H", help="Your handle. Defaults to your hub identity."
    ),
) -> None:
    """Load a pattern as a new room, paused.

    Example:
        mycelium pattern use approval-gate-agent --from https://github.com/<org>/<pattern-pack>
    """
    try:
        config = MyceliumConfig.load()
        pack = fetch_pack(source)
        scenario = pack.load(pattern)
        me = identity.resolve_actor(config, override=handle_flag)
        json_out = bool(ctx.obj and ctx.obj.get("json"))

        if dry_run:
            plan = build_plan(scenario, room or pattern, me)
            if json_out:
                console.print(json_module.dumps(plan.as_dict(), indent=2))
            else:
                _print_plan(plan, dry=True)
            return

        with hub_client(config, handle=me) as client:
            name = free_room_name(client, room or pattern, exact=room is not None)
            plan = build_plan(scenario, name, me)
            key, episode = load(client, plan, private=private, run=run)

        if json_out:
            console.print(
                json_module.dumps({**plan.as_dict(), "key": key, "episode": episode, "ran": run})
            )
            return
        _print_plan(plan, dry=False)
        _print_next(plan, key, run=run)
    except PatternError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except SwarmError as exc:
        console.print(f"[red]Error:[/red] {exc}\n[dim]The room was removed.[/dim]")
        raise typer.Exit(1) from exc
    except typer.Exit:
        raise
    except Exception as e:
        print_error(e, verbose=bool(ctx.obj and ctx.obj.get("verbose")))
        raise typer.Exit(1) from None


def _print_plan(plan: Plan, *, dry: bool) -> None:
    verb = "Would create" if dry else "Loaded"
    console.print(f"[bold]{verb}[/bold] room [cyan]{plan.room}[/cyan]: {plan.scenario.room.title}")
    for handle, kind, _ in plan.engines:
        console.print(f"  [dim]{kind:<11}[/dim] @{handle}")
    human = next((m for m in plan.scenario.members if m.kind == HUMAN), None)
    if human:
        console.print(f"  [dim]{'you':<11}[/dim] @{plan.me}")
    console.print(f"  [dim]{len(plan.memories)} memories, task:[/dim] {plan.scenario.task.title}")


def _print_next(plan: Plan, key: str, *, run: bool) -> None:
    summon = plan.scenario.summon
    if plan.summon is None or summon is None:
        console.print("\n[dim]No flow to run: the room is ready to work in.[/dim]")
    elif run:
        console.print(f"\n[green]Started[/green] {summon.flow} on {key}.")
    else:
        ask = plan.summon.removeprefix(f"@{CONDUCTOR} ")
        console.print("\nIt is [bold]paused[/bold]. Start it with:")
        console.print(f'  mycelium board coordinate {key} {CONDUCTOR} "{ask}" --room {plan.room}')
    console.print(f"\nOpen it: mycelium watch --room {plan.room}")
