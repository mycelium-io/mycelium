# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What the hub knows about a runner and the jobs it was sent.

``mycelium runner status`` and the agent controls read these. The runner's
own side of the conversation (hello, the job long-poll, reports) lives in
``mycelium.runner.daemon``. A refusal raises :class:`~mycelium.exceptions.HubError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mycelium_backend_client import Client
    from mycelium_backend_client.models import RunnerJobRead, RunnerRead


def read(client: Client, runner_id: str) -> RunnerRead:
    """One runner as the hub last heard from it. A runner the hub never heard
    from, or one the caller doesn't own, is a 404."""
    from mycelium.client import answered
    from mycelium_backend_client.api.runners import get_runner_api_runners_runner_id_get
    from mycelium_backend_client.models import RunnerRead

    resp = get_runner_api_runners_runner_id_get.sync_detailed(runner_id, client=client)
    return answered(resp, RunnerRead)


def job(client: Client, runner_id: str, job_id: str) -> RunnerJobRead:
    """One job sent to a runner, with its status and what it reported."""
    from mycelium.client import answered
    from mycelium_backend_client.api.runners import (
        get_job_api_runners_runner_id_jobs_job_id_get as job_api,
    )
    from mycelium_backend_client.models import RunnerJobRead

    return answered(job_api.sync_detailed(runner_id, job_id, client=client), RunnerJobRead)
