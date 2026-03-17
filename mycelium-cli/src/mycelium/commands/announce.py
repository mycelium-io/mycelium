"""
Announce command for Mycelium CLI.

Broadcast status to room.
"""

import json as json_module

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError, MyceliumError
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
        from mycelium_backend_client import Client
        from mycelium_backend_client.api.messages import send_message_rooms_room_name_messages_post as send_api
        from mycelium_backend_client.models import MessageCreate

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

        client = Client(base_url=config.server.api_url, raise_on_unexpected_status=True)
        with client:
            body = MessageCreate(
                sender_handle=handle,
                message_type="announce",
                content=message,
            )
            result = send_api.sync(room_name=room_name, client=client, body=body)

        if json_output and result:
            msg_dict = result.to_dict() if hasattr(result, "to_dict") else str(result)
            typer.echo(json_module.dumps(msg_dict, indent=2, default=str))
        else:
            typer.secho("Announced:", fg=typer.colors.GREEN)
            typer.echo(f"  {handle}: {message}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
