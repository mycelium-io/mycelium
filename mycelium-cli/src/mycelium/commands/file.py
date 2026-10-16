# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
File commands: the files a room keeps, the ``uploads/`` memory namespace promoted.

An upload is a memory at ``uploads/<name>`` plus the file it names, kept on the
hub. People add files in the app; agents add and fetch them here. A message
links one as ``[[uploads/<name>]]``, which is what an agent sees in a wake or an
``await``, so every command here takes that form as readily as the bare name.
Everything resolves against the hub over HTTP; a spoke keeps no copy.
"""

import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import typer
from rich.console import Console
from rich.markup import escape

from mycelium.cli_options import acts_as, confirms, emits_json, in_room, paged
from mycelium.client import hub_client, hub_error_detail, typed_client
from mycelium.config import MyceliumConfig
from mycelium.doc_ref import doc_ref
from mycelium_backend_client.errors import UnexpectedStatus

app = typer.Typer(
    # Help is Rich markup, where `[` opens a tag, so a literal link is escaped.
    help="Add, fetch and list the files a room keeps (its uploads/). A message links one as \\[\\[uploads/<name>]].",
    no_args_is_help=True,
)
REF_HELP = "The file: its name, uploads/<name>, or \\[\\[uploads/<name>]]"
console = Console()
err_console = Console(stderr=True)

UPLOADS_PREFIX = "uploads/"

# Uploads can be large and slow to clean (an image is re-encoded on the hub).
_TRANSFER_TIMEOUT_S = 300.0


def _get_client():
    """The shared authenticated OpenAPI client (see ``mycelium.client``)."""
    return typed_client()


def _raw_client(handle: str | None = None) -> httpx.Client:
    """A raw client for the multipart upload and the streamed download."""
    return hub_client(timeout=_TRANSFER_TIMEOUT_S, handle=handle)


def _hub_url() -> str:
    return MyceliumConfig.load().server.api_url


@contextmanager
def _hub_session(client_factory: Any = None) -> Iterator[Any]:
    """Yield a hub client, reporting an unreachable hub instead of raising."""
    with (client_factory or _get_client)() as client:
        try:
            yield client
        except httpx.HTTPError as exc:
            err_console.print(f"[red]Error:[/red] can't reach the hub at {_hub_url()}: {exc}")
            err_console.print(
                "[dim]Check the hub is running ('mycelium status'), or point "
                "server.api_url at it.[/dim]"
            )
            raise typer.Exit(1) from exc
        except UnexpectedStatus as exc:
            if exc.status_code == 404:
                err_console.print(
                    "[red]Not found.[/red] See the room's files with: mycelium file ls"
                )
                raise typer.Exit(1) from exc
            detail = hub_error_detail(exc.content)
            suffix = f": {detail}" if detail else "."
            err_console.print(
                f"[red]Error:[/red] hub at {_hub_url()} returned HTTP {exc.status_code}{suffix}"
            )
            raise typer.Exit(1) from exc


def _echo_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def upload_name(ref: str) -> str:
    """The upload's name from what a person or agent typed.

    ``spec.pdf``, ``uploads/spec.pdf``, ``[[uploads/spec.pdf]]`` and
    ``myc://uploads/spec.pdf`` all name the same upload.
    """
    text = ref.strip()
    if match := re.fullmatch(r"!?\[\[(.+?)\]\]", text):
        text = match.group(1).strip()
    text = text.removeprefix("myc://")
    return text.removeprefix(UPLOADS_PREFIX)


def link_for(name: str) -> str:
    """What to put in a message so it links the upload."""
    return f"[[{UPLOADS_PREFIX}{name}]]"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def _segment(text: str) -> str:
    return quote(text, safe="")


@doc_ref(
    usage="mycelium file upload <path>... [--room <room>] [--as <handle>]",
    desc="Add files to a room. Prints the <code>[[uploads/&lt;name&gt;]]</code> link for each, to put in a message. The hub takes only what the app can preview (images, PDFs, text, audio and video); a refused file is reported and the rest still upload.",
    group="file",
)
@app.command(name="upload")
@in_room("room")
@acts_as("handle")
@emits_json("as_json")
def file_upload(
    paths: list[Path] = typer.Argument(..., help="Files to add"),
    room: str | None = None,
    handle: str | None = None,
    as_json: bool = False,
) -> None:
    """Add one or more files to the room. Each prints the link to paste in a message."""
    assert room is not None
    added: list[dict[str, Any]] = []
    failed = 0
    with _hub_session(lambda: _raw_client(handle)) as client:
        for path in paths:
            if not path.is_file():
                err_console.print(f"[red]Not a file:[/red] {path}")
                failed += 1
                continue
            with path.open("rb") as fh:
                resp = client.post(
                    f"/api/rooms/{_segment(room)}/uploads",
                    files={"file": (path.name, fh, "application/octet-stream")},
                    data={"created_by": handle or ""},
                )
            if resp.status_code != 201:
                detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
                err_console.print(f"[red]Refused:[/red] {detail}")
                failed += 1
                continue
            record = resp.json()
            added.append(record)
            if not as_json:
                console.print(
                    f"[green]Added:[/green] {record['name']}  "
                    f"[dim]{record['kind']}, {human_size(record['size'])}[/dim]"
                )
                typer.echo(f"  {link_for(record['name'])}")
    if as_json:
        _echo_json(added)
    if failed:
        raise typer.Exit(1)


def _record(room: str, name: str) -> Any:
    from mycelium_backend_client.api.uploads import (
        get_upload_api_rooms_room_name_uploads_name_get as get_api,
    )

    with _hub_session() as client:
        return get_api.sync(room_name=room, name=name, client=client)


@doc_ref(
    usage="mycelium file download <name> [-o <path>] [--force]",
    desc="Save a room's file. <code>&lt;name&gt;</code> can be written as it appears in a message, <code>[[uploads/&lt;name&gt;]]</code>. Saves to the file's own name in this folder by default; <code>-o -</code> writes it to stdout.",
    group="file",
)
@app.command(name="download")
@in_room("room")
def file_download(
    ref: str = typer.Argument(..., help=REF_HELP),
    room: str | None = None,
    output: str | None = typer.Option(
        None, "--output", "-o", help="Where to save it (default: its own name here; '-' for stdout)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Replace a file already at the output path"
    ),
) -> None:
    """Save a file from the room."""
    assert room is not None
    name = upload_name(ref)
    record = _record(room, name)
    to_stdout = output == "-"
    target = None if to_stdout else Path(output or Path(record.filename).name or name)
    if target is not None and target.is_dir():
        target = target / (Path(record.filename).name or name)
    if target is not None and target.exists() and not force:
        err_console.print(f"[red]Already exists:[/red] {target}  [dim](--force replaces it)[/dim]")
        raise typer.Exit(1)

    url = f"/api/rooms/{_segment(room)}/uploads/{_segment(name)}/raw"
    with (
        _hub_session(_raw_client) as client,
        client.stream("GET", url, params={"download": "1"}) as resp,
    ):
        if resp.status_code != 200:
            resp.read()
            detail = hub_error_detail(resp.content) or f"HTTP {resp.status_code}"
            err_console.print(f"[red]Error:[/red] {detail}")
            raise typer.Exit(1)
        if to_stdout:
            for chunk in resp.iter_bytes():
                sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            return
        assert target is not None
        partial = target.with_name(f".{target.name}.part")
        with partial.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
        partial.replace(target)
    console.print(f"[green]Saved:[/green] {target}  [dim]{human_size(record.size)}[/dim]")


@doc_ref(
    usage="mycelium file ls [--limit <n>]",
    desc="List a room's files, newest first.",
    group="file",
)
@app.command(name="ls")
@in_room("room")
@emits_json("as_json")
@paged("limit", default=50)
def file_ls(
    room: str | None = None,
    as_json: bool = False,
    limit: int = 50,
) -> None:
    """List the room's files from the hub."""
    from mycelium_backend_client.api.uploads import (
        list_room_uploads_api_rooms_room_name_uploads_get as list_api,
    )

    assert room is not None
    with _hub_session() as client:
        resp = list_api.sync(room_name=room, client=client)
    items = list(getattr(resp, "uploads", None) or [])[: max(limit, 0)]
    if as_json:
        _echo_json([u.to_dict() for u in items])
        return
    if not items:
        console.print("[dim]No files yet. Add one with: mycelium file upload <path>[/dim]")
        return
    total = getattr(resp, "total", len(items))
    console.print(f"[bold]Files[/bold] ({len(items)} of {total})\n")
    for u in items:
        when = u.created_at.strftime("%Y-%m-%d %H:%M")
        console.print(
            f"[cyan]{u.name}[/cyan]  [dim]{u.kind.value}  {human_size(u.size)}  "
            f"{u.created_by}  {when}[/dim]"
        )


@doc_ref(
    usage="mycelium file show <name>",
    desc="Show a file's record: its type, size, who added it and the link to it.",
    group="file",
)
@app.command(name="show")
@in_room("room")
@emits_json("as_json")
def file_show(
    ref: str = typer.Argument(..., help=REF_HELP),
    room: str | None = None,
    as_json: bool = False,
) -> None:
    """Show one file's record."""
    assert room is not None
    record = _record(room, upload_name(ref))
    if as_json:
        _echo_json(record.to_dict())
        return
    console.print(f"[cyan]{record.name}[/cyan]  [dim]{record.filename}[/dim]")
    console.print(f"  {record.kind.value}, {record.content_type}, {human_size(record.size)}")
    console.print(f"  added by {record.created_by}, {record.created_at:%Y-%m-%d %H:%M}")
    console.print(f"  link: {escape(link_for(record.name))}")
    console.print(f"  [dim]sha256 {record.sha256}[/dim]")


@doc_ref(
    usage="mycelium file rm <name> [--yes]",
    desc="Remove a file from a room. Messages that linked it keep the link, which then finds nothing.",
    group="file",
)
@app.command(name="rm")
@in_room("room")
@confirms("yes")
def file_rm(
    ref: str = typer.Argument(..., help=REF_HELP),
    room: str | None = None,
    yes: bool = False,
) -> None:
    """Remove a file from the room."""
    from mycelium_backend_client.api.uploads import (
        delete_upload_api_rooms_room_name_uploads_name_delete as delete_api,
    )

    assert room is not None
    name = upload_name(ref)
    if not yes and not typer.confirm(f"Remove {name} from room '{room}'?"):
        raise typer.Exit(0)
    with _hub_session() as client:
        resp = delete_api.sync_detailed(room_name=room, name=name, client=client)
    if resp.status_code == 404:
        err_console.print(f"[red]Not found:[/red] {name}")
        raise typer.Exit(1)
    console.print(f"[green]Removed:[/green] {name}")
