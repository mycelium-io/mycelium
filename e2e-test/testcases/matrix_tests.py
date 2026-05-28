"""Matrix communication tests.

Maps to original test 07.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from pyats import aetest

from libs.environment import EnvironmentInfo

log = logging.getLogger(__name__)


class MatrixCommunication(aetest.Testcase):
    """Test 07: Matrix API messaging to #agents:local."""

    groups = ["matrix"]

    @aetest.setup
    def check_matrix(self, env):
        if env.skip_matrix_tests:
            self.skipped("Matrix not reachable")

    @aetest.test
    def matrix_messaging(self, steps, api, matrix_url, matrix_config):
        """Verify Matrix room is reachable and a message round-trip works."""
        from libs.matrix_client import (
            MatrixClient,
            check_matrix_reachable,
            get_observer_token,
        )

        with steps.start("Verify Matrix reachable") as step:
            if not check_matrix_reachable(matrix_url):
                step.failed("Matrix homeserver not reachable")

        room_alias = matrix_config.get("test_room_alias", "#agents:local")
        room_id = matrix_config.get("test_room_id")
        shared_secret = matrix_config.get("shared_secret", "")

        with steps.start("Obtain observer token") as step:
            if not shared_secret:
                step.failed("No Matrix shared_secret configured — cannot create observer")
            try:
                token = asyncio.run(get_observer_token(matrix_url, shared_secret))
                log.info("Observer token obtained")
            except Exception as exc:
                step.failed(f"Observer token acquisition failed: {exc}")

        with steps.start("Resolve agent room") as step:
            if room_alias:
                resolved = asyncio.run(
                    _resolve_alias(matrix_url, token, room_alias)
                )
                if resolved:
                    if room_id and resolved != room_id:
                        log.info(
                            "Alias %s resolved to %s (overriding configured %s)",
                            room_alias, resolved, room_id,
                        )
                    room_id = resolved
            if not room_id:
                step.failed("No room_id configured and alias resolution failed")
            log.info("Matrix room: alias=%s id=%s", room_alias, room_id)

        with steps.start("Send and verify test message") as step:
            marker = f"e2e-matrix-{uuid.uuid4().hex[:8]}"
            try:
                sent, messages = asyncio.run(
                    _matrix_roundtrip(matrix_url, token, room_id, marker)
                )
                if not sent:
                    step.failed("Failed to send test message to Matrix room")
                found = any(marker in m.get("body", "") for m in messages)
                if not found:
                    step.failed(
                        f"Test marker '{marker}' not found in last "
                        f"{len(messages)} messages"
                    )
                log.info("Matrix round-trip verified: marker=%s", marker)
            except Exception as exc:
                step.failed(f"Matrix round-trip failed: {exc}")


async def _resolve_alias(homeserver: str, token: str, alias: str) -> str | None:
    """Resolve a Matrix room alias to its room ID."""
    from libs.matrix_client import MatrixClient

    client = MatrixClient(homeserver, token)
    try:
        return await client.resolve_room_alias(alias)
    finally:
        await client.close()


async def _matrix_roundtrip(
    homeserver: str, token: str, room_id: str, marker: str,
) -> tuple[bool, list[dict]]:
    """Join room, send a message, read it back."""
    from libs.matrix_client import MatrixClient
    import httpx

    async with httpx.AsyncClient(
        base_url=homeserver,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    ) as http:
        await http.post(
            f"/_matrix/client/v3/join/{room_id}",
            json={},
        )

    client = MatrixClient(homeserver, token)
    try:
        await client.send_message(room_id, f"[e2e-test] ping {marker}")
        messages, _ = await client.read_messages(room_id, limit=10)
        return True, messages
    finally:
        await client.close()
