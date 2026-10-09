# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Schedule commands: an agent's recurring check-in, kept and fired by the hub.

The hub owns a schedule, so it outlives the agent's session and anyone in the
room can see it, pause it or run it. Each run first asks a cheap pre-check (a
query the hub answers in code); only a check that finds something wakes the
agent, through the same path a mention does. A quiet run costs no model turn
and posts nothing to the room.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

from mycelium.cli_options import acts_as, confirms, emits_json, in_room
from mycelium.client import hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium.text_input import takes_text

app = typer.Typer(
    help="Give an agent a recurring check-in the hub fires: every N minutes or on a cron line, with a cheap pre-check before it wakes.",
    no_args_is_help=True,
)
console = Console()

#: How each run result reads, and its color; the same words the app uses.
_RESULT = {
    "woke": ("woke agent", "green"),
    "quiet": ("nothing to do", "dim"),
    "held": ("already queued", "yellow"),
    "busy": ("agent busy", "yellow"),
    "error": ("check failed", "red"),
}


def _call(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a typed-client endpoint; say the hub's reason and exit on a refusal."""
    with typed_client() as client:
        try:
            resp = fn(client=client, **kwargs)
        except httpx.HTTPError as exc:
            url = MyceliumConfig.load().server.api_url
            console.print(f"[red]Error:[/red] can't reach the hub at {url}: {exc}")
            raise typer.Exit(1) from exc
    if resp.status_code >= 400:
        detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1)
    return json.loads(resp.content) if resp.content else None


def _echo_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def _when(s: dict[str, Any]) -> str:
    return f"every {s['every']}" if s.get("every") else f"cron {s.get('cron')}"


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _rel(raw: str | None, now: datetime) -> str:
    """``in 12m`` / ``3h ago`` / ``-``."""
    stamp = _parse(raw)
    if stamp is None:
        return "-"
    seconds = int((stamp - now).total_seconds())
    span = abs(seconds)
    if span < 60:
        text = f"{span}s"
    elif span < 3600:
        text = f"{span // 60}m"
    elif span < 172800:
        text = f"{span // 3600}h"
    else:
        text = f"{span // 86400}d"
    return f"in {text}" if seconds >= 0 else f"{text} ago"


def _result(value: str | None) -> str:
    if not value:
        return "[dim]-[/dim]"
    word, style = _RESULT.get(value, (value, "white"))
    return f"[{style}]{word}[/]"


@doc_ref(
    usage='mycelium schedule add <name> "<prompt>" (--every 30m | --cron "<line>") [--check <check>] [--task <row>] [--for <handle>]',
    desc=(
        "Give an agent a schedule the hub fires. <code>--check</code> runs first and wakes the agent "
        "only when it finds something: <code>mentions</code>, <code>assigned</code>, "
        "<code>stale</code> (your leases), <code>silent</code> (someone else's lapsed hold), "
        "<code>task</code> (the bound task's thread moved), <code>search:&lt;query&gt;</code>, "
        "or <code>always</code>. Expires after a week unless renewed."
    ),
    group="schedule",
)
@app.command(name="add")
@takes_text("prompt", "What the agent is told when the schedule wakes it.", noun="prompt")
@in_room("room")
@acts_as("handle")
@emits_json("as_json")
def schedule_add(
    name: str = typer.Argument(..., help="Schedule slug (kebab-case, e.g. 'board-check')"),
    prompt: str = typer.Argument(..., help="What the agent is told when it wakes"),
    every: str | None = typer.Option(None, "--every", "-e", help="Interval: 30m, 2h, 1d"),
    cron: str | None = typer.Option(None, "--cron", help="Five-field cron line, in UTC"),
    check: str | None = typer.Option(
        None, "--check", "-c", help="Pre-check before the model wakes (default: always)"
    ),
    task: str | None = typer.Option(None, "--task", "-t", help="Bind it to a board row"),
    owner: str | None = typer.Option(
        None, "--for", help="The agent it wakes (default: whoever is acting)"
    ),
    days: float | None = typer.Option(None, "--days", help="Days until it must be renewed"),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Give an agent a recurring check-in the hub fires."""
    from mycelium_backend_client.api.schedules import (
        create_schedule_api_rooms_room_name_schedules_post as create_api,
    )
    from mycelium_backend_client.models import ScheduleCreate

    assert room is not None
    body = ScheduleCreate(
        name=name,
        owner=(owner or handle or "").lstrip("@"),
        every=every,
        cron=cron,
        prompt=prompt,
        check=check,
        task=task,
        expires_in_days=days,
        created_by=handle,
    )
    data = _call(create_api.sync_detailed, room_name=room, body=body)
    if as_json:
        _echo_json(data)
        return
    now = datetime.now(UTC)
    console.print(
        f"[green]Scheduled[/green] {data['name']} for @{data['owner']}: {_when(data)}, "
        f"check {data['check']}, next {_rel(data.get('next_run'), now)}, "
        f"expires {_rel(data.get('expires_at'), now)}"
    )


@doc_ref(
    usage="mycelium schedule ls [--for <handle>]",
    desc="A room's schedules: who each wakes, when, its check, its status and its last run.",
    group="schedule",
)
@app.command(name="ls")
@in_room("room")
@emits_json("as_json")
def schedule_ls(
    owner: str | None = typer.Option(None, "--for", help="Only this agent's schedules"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """List a room's schedules."""
    from mycelium_backend_client.api.schedules import (
        list_schedules_api_rooms_room_name_schedules_get as list_api,
    )

    assert room is not None
    data = _call(list_api.sync_detailed, room_name=room, owner=owner.lstrip("@") if owner else None)
    items = data.get("schedules", [])
    if as_json:
        _echo_json(items)
        return
    if not items:
        console.print(f"[dim]No schedules in {room}[/dim]")
        return
    now = datetime.now(UTC)
    table = Table(box=None, pad_edge=False, header_style="dim")
    for col in ("name", "agent", "schedule", "check", "status", "next run", "last run"):
        table.add_column(col, no_wrap=col in ("name", "agent"))
    for s in items:
        state = s["state"]
        style = {"active": "green", "paused": "yellow", "expired": "red"}.get(state, "white")
        last = f"{_result(s.get('last_result'))} [dim]{_rel(s.get('last_run'), now)}[/dim]"
        table.add_row(
            f"[cyan]{s['name']}[/cyan]",
            f"@{s['owner']}",
            _when(s),
            s["check"],
            f"[{style}]{state}[/]",
            _rel(s.get("next_run"), now) if state == "active" else "-",
            last if s.get("last_run") else "[dim]never[/dim]",
        )
    console.print(table)


@doc_ref(
    usage="mycelium schedule show <name>",
    desc="One schedule and its recent runs, newest first.",
    group="schedule",
)
@app.command(name="show")
@in_room("room")
@emits_json("as_json")
def schedule_show(
    name: str = typer.Argument(..., help="Schedule name"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Show one schedule and its run history."""
    from mycelium_backend_client.api.schedules import (
        get_schedule_api_rooms_room_name_schedules_name_get as get_api,
    )

    assert room is not None
    s = _call(get_api.sync_detailed, room_name=room, name=name)
    if as_json:
        _echo_json(s)
        return
    now = datetime.now(UTC)
    console.print(f"[cyan]{s['name']}[/cyan]  @{s['owner']}  [dim]{s['state']}[/dim]")
    console.print(f"  when     {_when(s)}  (next {_rel(s.get('next_run'), now)})")
    console.print(f"  check    {s['check']}")
    if s.get("task"):
        console.print(f"  task     {s['task']}")
    console.print(f"  expires  {_rel(s.get('expires_at'), now)}")
    console.print(f"  runs     {s['runs']} total, {s['wakes']} woke the agent")
    if s.get("prompt"):
        console.print(f"\n{s['prompt']}")
    history = s.get("history") or []
    if not history:
        return
    table = Table(box=None, pad_edge=False, header_style="dim", title_justify="left")
    for col in ("when", "result", "details"):
        table.add_column(col, no_wrap=col != "details")
    for run in history:
        notes = list(run.get("found") or [])
        if run.get("detail"):
            notes.append(f"[red]{run['detail']}[/red]")
        if run.get("missed"):
            notes.append(f"[dim]caught up {run['missed']} missed runs[/dim]")
        manual = " [dim](manual)[/dim]" if run.get("trigger") == "manual" else ""
        table.add_row(
            _rel(run["at"], now),
            _result(run["result"]) + manual,
            "\n".join(notes) or "[dim]-[/dim]",
        )
    console.print()
    console.print(table)


def _patch(room: str, name: str, **fields: Any) -> dict[str, Any]:
    from mycelium_backend_client.api.schedules import (
        update_schedule_api_rooms_room_name_schedules_name_patch as update_api,
    )
    from mycelium_backend_client.models import ScheduleUpdate

    body = ScheduleUpdate.from_dict({k: v for k, v in fields.items() if v is not None})
    return _call(update_api.sync_detailed, room_name=room, name=name, body=body)


@doc_ref(
    usage='mycelium schedule edit <name> [--every 1h | --cron "<line>"] [--check <check>] [--prompt <text>] [--task <row>]',
    desc="Change a schedule's timing, pre-check, prompt or task. Only what is given changes.",
    group="schedule",
)
@app.command(name="edit")
@in_room("room")
@emits_json("as_json")
def schedule_edit(
    name: str = typer.Argument(..., help="Schedule name"),
    every: str | None = typer.Option(None, "--every", "-e", help="Interval: 30m, 2h, 1d"),
    cron: str | None = typer.Option(None, "--cron", help="Five-field cron line, in UTC"),
    check: str | None = typer.Option(None, "--check", "-c", help="Pre-check before it wakes"),
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="What the agent is told"),
    task: str | None = typer.Option(None, "--task", "-t", help="Bind to a row ('' unbinds)"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Edit a schedule."""
    assert room is not None
    data = _patch(room, name, every=every, cron=cron, check=check, prompt=prompt, task=task)
    if as_json:
        _echo_json(data)
        return
    console.print(f"[green]Updated[/green] {name}: {_when(data)}, check {data['check']}")


def _toggle(room: str, name: str, *, paused: bool, as_json: bool) -> None:
    data = _patch(room, name, paused=paused)
    if as_json:
        _echo_json(data)
        return
    word = "Paused" if paused else "Resumed"
    nxt = "" if paused else f", next {_rel(data.get('next_run'), datetime.now(UTC))}"
    console.print(f"[green]{word}[/green] {name}{nxt}")


@doc_ref(
    usage="mycelium schedule pause <name>",
    desc="Stop a schedule firing until it is resumed.",
    group="schedule",
)
@app.command(name="pause")
@in_room("room")
@emits_json("as_json")
def schedule_pause(
    name: str = typer.Argument(..., help="Schedule name"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Pause a schedule."""
    assert room is not None
    _toggle(room, name, paused=True, as_json=as_json)


@doc_ref(
    usage="mycelium schedule resume <name>",
    desc="Start a paused schedule again; its clock restarts from now.",
    group="schedule",
)
@app.command(name="resume")
@in_room("room")
@emits_json("as_json")
def schedule_resume(
    name: str = typer.Argument(..., help="Schedule name"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Resume a paused schedule."""
    assert room is not None
    _toggle(room, name, paused=False, as_json=as_json)


@doc_ref(
    usage="mycelium schedule renew <name> [--days 7]",
    desc="Push a schedule's expiry out again from now (it stops firing once it expires).",
    group="schedule",
)
@app.command(name="renew")
@in_room("room")
@emits_json("as_json")
def schedule_renew(
    name: str = typer.Argument(..., help="Schedule name"),
    days: float | None = typer.Option(
        None, "--days", help="Days from now (hub default if omitted)"
    ),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Renew a schedule's expiry."""
    assert room is not None
    data = _patch(room, name, renew=True, renew_days=days)
    if as_json:
        _echo_json(data)
        return
    console.print(
        f"[green]Renewed[/green] {name}: expires {_rel(data.get('expires_at'), datetime.now(UTC))}"
    )


@doc_ref(
    usage="mycelium schedule run <name> [--wake]",
    desc="Run a schedule now: its pre-check, then the wake if it found anything. <code>--wake</code> skips the check. Its timetable is left alone.",
    group="schedule",
)
@app.command(name="run")
@in_room("room")
@emits_json("as_json")
def schedule_run(
    name: str = typer.Argument(..., help="Schedule name"),
    wake: bool = typer.Option(False, "--wake", "-w", help="Skip the pre-check and wake the agent"),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Run a schedule now."""
    from mycelium_backend_client.api.schedules import (
        run_schedule_api_rooms_room_name_schedules_name_run_post as run_api,
    )
    from mycelium_backend_client.models import ScheduleRunRequest

    assert room is not None
    run = _call(
        run_api.sync_detailed, room_name=room, name=name, body=ScheduleRunRequest(wake=wake)
    )
    if as_json:
        _echo_json(run)
        return
    console.print(f"{name}: {_result(run['result'])}")
    for line in run.get("found") or []:
        console.print(f"  [dim]- {line}[/dim]")
    if run.get("detail"):
        console.print(f"  [red]{run['detail']}[/red]")


@doc_ref(usage="mycelium schedule rm <name>", desc="Delete a schedule.", group="schedule")
@app.command(name="rm")
@in_room("room")
@confirms("yes")
def schedule_rm(
    name: str = typer.Argument(..., help="Schedule name"),
    room: str | None = None,
    yes: bool = False,
) -> None:
    """Delete a schedule."""
    from mycelium_backend_client.api.schedules import (
        delete_schedule_api_rooms_room_name_schedules_name_delete as delete_api,
    )

    assert room is not None
    if not yes and not typer.confirm(f"Delete schedule {name} in {room}?"):
        raise typer.Exit(0)
    _call(delete_api.sync_detailed, room_name=room, name=name)
    console.print(f"[green]Deleted[/green] {name}")
