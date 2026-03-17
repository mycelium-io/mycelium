"""
Send command for Mycelium CLI.

Send a message to an agent or broadcast to the room.
"""

import json as json_module

import typer

from mycelium.config import MyceliumConfig
from mycelium.error_handler import print_error
from mycelium.exceptions import ConfigNotFoundError, MyceliumError
from mycelium.identity import get_current_handle


def send(
    ctx: typer.Context,
    to: str = typer.Argument(
        ...,
        help="Recipient handle (@handle or @all)",
    ),
    message: str = typer.Argument(
        ...,
        help="Message body",
    ),
) -> None:
    """
    Send message to agent or broadcast.

    Examples:
        mycelium send @alpha#a1b2 "Can you check CFE-123?"
        mycelium send @all "Deploy complete"
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

        recipient = to.lstrip("@")
        if recipient == "all":
            message_type = "broadcast"
            recipient_handle = None
        else:
            message_type = "direct"
            recipient_handle = recipient

        client = Client(base_url=config.server.api_url, raise_on_unexpected_status=True)
        with client:
            body = MessageCreate(
                sender_handle=handle,
                message_type=message_type,
                content=message,
                recipient_handle=recipient_handle,
            )
            result = send_api.sync(room_name=room_name, client=client, body=body)

        if json_output and result:
            msg_dict = result.to_dict() if hasattr(result, "to_dict") else str(result)
            typer.echo(json_module.dumps(msg_dict, indent=2, default=str))
        else:
            if message_type == "broadcast":
                typer.secho("Broadcasted:", fg=typer.colors.GREEN)
                typer.echo(f"  {handle} -> @all: {message}")
            else:
                typer.secho("Sent:", fg=typer.colors.GREEN)
                typer.echo(f"  {handle} -> @{recipient_handle}: {message}")

    except Exception as e:
        verbose = ctx.obj.get("verbose", False) if ctx.obj else False
        print_error(e, verbose=verbose)
        raise typer.Exit(1) from None
