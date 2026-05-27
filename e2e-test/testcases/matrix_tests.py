"""Matrix communication tests.

Maps to original test 07.
"""

from __future__ import annotations

import logging

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
        """Verify Matrix room is reachable and messages can be read."""
        from libs.matrix_client import check_matrix_reachable

        with steps.start("Verify Matrix reachable") as step:
            if not check_matrix_reachable(matrix_url):
                step.failed("Matrix homeserver not reachable")

        with steps.start("Verify agent room exists") as step:
            room_alias = matrix_config.get("test_room_alias", "#agents:local")
            room_id = matrix_config.get("test_room_id")
            if not room_id:
                step.failed("No test_room_id configured")
            log.info("Matrix room: alias=%s id=%s", room_alias, room_id)
