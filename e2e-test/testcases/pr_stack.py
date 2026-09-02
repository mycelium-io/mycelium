"""PR checks — stack health tests.

Gates: every PR. No LLM required. No agents.

Tests:
  - Backend /health reachable and returns expected shape
  - SLIM node reachable
  - Room lifecycle: create → list → delete
"""

from __future__ import annotations

import logging
import uuid

from pyats import aetest

from libs.environment import EnvironmentInfo
from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI

log = logging.getLogger(__name__)

parameters = {}


class BackendHealth(aetest.Testcase):
    """Backend /health returns 200 with expected fields."""

    @aetest.test
    def health_reachable(self, api: MyceliumAPI):
        status, body = api.health()
        assert status == 200, f"Expected 200, got {status}: {body}"

    @aetest.test
    def health_shape(self, api: MyceliumAPI):
        health = api.health_json()
        assert health is not None, "Could not parse health JSON"
        assert "status" in health or "slim" in health or "llm" in health, (
            f"Unexpected health shape: {health}"
        )

    @aetest.test
    def slim_node_reachable(self, env: EnvironmentInfo):
        assert env.slim_reachable, (
            f"SLIM node not reachable (endpoint={env.slim_endpoint}). "
            "Check that mycelium hub is running."
        )


class RoomLifecycle(aetest.Testcase):
    """Room CRUD: create, list, delete."""

    @aetest.setup
    def create_room(self, api: MyceliumAPI, testscript):
        self.room = f"qa-lifecycle-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        status, data = api.create_room(self.room, description="lifecycle test")
        assert status in (200, 201), f"room create failed: status={status} data={data}"
        log.info("Created room: %s", self.room)

    @aetest.test
    def room_appears_in_list(self, api: MyceliumAPI):
        status, data = api.list_rooms()
        assert status == 200, f"list_rooms failed: {status}"
        names = [r.get("name") for r in (data if isinstance(data, list) else [])]
        assert self.room in names, f"{self.room!r} not in room list: {names}"

    @aetest.test
    def room_get(self, api: MyceliumAPI):
        status, data = api.get_room(self.room)
        assert status == 200, f"get_room failed: {status}"
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"

    @aetest.test
    def room_messages_empty(self, api: MyceliumAPI):
        status, data = api.get_room_messages(self.room, limit=10)
        assert status == 200, f"get_room_messages failed: {status}"
        assert isinstance(data, list), f"Expected list, got {type(data)}"

    @aetest.cleanup
    def delete_room(self, api: MyceliumAPI):
        status, _ = api.delete_room(self.room)
        assert 200 <= status < 300 or status == 404, f"delete_room unexpected: {status}"
        log.info("Deleted room: %s", self.room)


class CLIBasics(aetest.Testcase):
    """CLI smoke tests: doctor, room ls, network."""

    @aetest.test
    def doctor_runs(self, cli: MyceliumCLI):
        r = cli.doctor()
        # doctor may return non-zero if config is incomplete, but it should not crash
        assert r.returncode != -1, f"CLI doctor crashed or timed out: {r.error_message}"

    @aetest.test
    def room_ls_runs(self, cli: MyceliumCLI):
        r = cli.room_ls()
        assert r.ok, f"room ls failed: {r.error_message}"

    @aetest.test
    def network_status(self, cli: MyceliumCLI):
        r = cli.network()
        # network may not be parseable JSON on all builds; just assert it ran
        assert r.returncode != -1, f"mycelium network crashed: {r.error_message}"
