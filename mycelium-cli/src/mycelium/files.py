# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The files a room keeps on the hub (its ``uploads/``): adding, reading,
listing, downloading and removing them.

``mycelium file ...`` and :class:`mycelium.Room`'s ``files`` send these. A
refusal raises :class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mycelium.exceptions import HubError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

    from mycelium_backend_client import Client
    from mycelium_backend_client.models import UploadListResponse, UploadRead


def upload_file(http: Any, room: str, path: Path, handle: str | None) -> dict[str, Any]:
    """Add one file to the room through a raw ``httpx`` client, and return its record."""
    with path.open("rb") as fh:
        resp = http.post(
            f"/api/rooms/{quote(room, safe='')}/uploads",
            files={"file": (path.name, fh, "application/octet-stream")},
            data={"created_by": handle or ""},
        )
    if resp.status_code != 201:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return resp.json()


def record(client: Client, room: str, name: str) -> UploadRead:
    """One file's record: its name, kind, size and who added it."""
    from mycelium.client import answered
    from mycelium_backend_client.api.uploads import (
        get_upload_api_rooms_room_name_uploads_name_get as get_api,
    )
    from mycelium_backend_client.models import UploadRead

    return answered(get_api.sync_detailed(room_name=room, name=name, client=client), UploadRead)


def list_files(client: Client, room: str) -> UploadListResponse:
    """The room's files, newest first, with how many there are."""
    from mycelium.client import answered
    from mycelium_backend_client.api.uploads import (
        list_room_uploads_api_rooms_room_name_uploads_get as list_api,
    )
    from mycelium_backend_client.models import UploadListResponse

    return answered(list_api.sync_detailed(room_name=room, client=client), UploadListResponse)


def remove_file(client: Client, room: str, name: str) -> bool:
    """Remove a file from the room: ``False`` when the room has no such file."""
    from mycelium_backend_client.api.uploads import (
        delete_upload_api_rooms_room_name_uploads_name_delete as delete_api,
    )

    resp = delete_api.sync_detailed(room_name=room, name=name, client=client)
    if resp.status_code == 404:  # noqa: PLR2004
        return False
    if resp.status_code >= 400:  # noqa: PLR2004
        raise HubError(resp.status_code, resp.content)
    return True


@contextmanager
def download(http: httpx.Client, room: str, name: str) -> Iterator[httpx.Response]:
    """The file's bytes as a streamed response, through a raw ``httpx`` client."""
    url = f"/api/rooms/{quote(room, safe='')}/uploads/{quote(name, safe='')}/raw"
    with http.stream("GET", url, params={"download": "1"}) as resp:
        if resp.status_code != 200:  # noqa: PLR2004
            resp.read()
            raise HubError(resp.status_code, resp.content)
        yield resp
