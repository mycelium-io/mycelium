"""
Announce command for Mycelium CLI.

Broadcast status to room.
"""

import json as json_module

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError, MyceliumError
from mycelium.http_client import MyceliumHTTPClient
from mycelium.identity import get_current_handle


def announce(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="Status message to broadcast"),
) -> None:
    """
    Broadcast status to room.

    Examples:
        mycelium announce "Starting work on CVE-2024-1234"
        mycelium announce "CFN scan complete, results in room"
    """
    try:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False  # noqa: F841
        json_output = ctx.obj.get("json", False) if ctx.obj else False

        config_path = MyceliumConfig.get_config_path()
        if not config_path.exists():
            raise ConfigNotFoundError(str(config_path))

        config = MyceliumConfig.load()

        handle = get_current_handle(config)
        if not handle:
            raise MyceliumError(
                "No identity configured",
                suggestion="Run 'mycelium config set name <your-name>' to configure your identity",
            )

        from mycelium.utils import ensure_room_set
        room_name = ensure_room_set(config)

        with MyceliumHTTPClient(config=config) as client:
            response = client.post(
                f"/rooms/{room_name}/messages",
                json={
                    "sender_handle": handle,
                    "message_type": "announce",
                    "content": message,
                },
            )
            msg_data = response.json()

        if json_output:
            typer.echo(json_module.dumps(msg_data, indent=2, default=str))
        else:
            typer.secho("Announced:", fg=typer.colors.GREEN)
            typer.echo(f"  {handle}: {message}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
