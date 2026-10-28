# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What a stubbed generated ``sync_detailed`` hands back: the hub's whole answer."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from mycelium_backend_client.types import Response


def ok[T](parsed: T, status: int = 200) -> Response[T]:
    """The hub answering ``status`` with ``parsed``, as the generated client parses it."""
    return Response(status_code=HTTPStatus(status), content=b"", headers={}, parsed=parsed)


def posted(body: Any) -> Response[Any]:
    """The hub's 201 to a posted ``MessageCreate``: the message as it was recorded."""
    import datetime
    import uuid

    from mycelium_backend_client.models import MessageRead

    message = MessageRead(
        id=uuid.uuid4(),
        sender_handle=body.sender_handle,
        message_type=str(body.message_type),
        content=body.content,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    return ok(message, 201)


def refused(status: int, detail: Any = "refused") -> Response[Any]:
    """The hub refusing with ``status``: a ``Refusal`` carrying ``detail``."""
    from mycelium_backend_client.models import Refusal

    return Response(
        status_code=HTTPStatus(status),
        content=json.dumps({"detail": detail}).encode(),
        headers={},
        parsed=Refusal(detail=detail),
    )
