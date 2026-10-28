# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``sent_unparsed`` sends a generated route's own request, from the private
``_get_kwargs`` the generator writes into every route module. An upgrade of
openapi-python-client that renamed it would break the runner's loops, so this
fails first."""

from __future__ import annotations

import json

import httpx
import pytest

from mycelium.client import sent_unparsed
from mycelium_backend_client import Client
from mycelium_backend_client.api.memory import get_memory_api_rooms_room_name_memory_key_get
from mycelium_backend_client.api.participate import (
    confirm_delivery_api_rooms_room_name_await_confirm_post,
)
from mycelium_backend_client.api.runners import (
    get_runner_api_runners_runner_id_get,
    next_job_api_runners_runner_id_jobs_next_get,
    report_job_api_runners_runner_id_jobs_job_id_patch,
    runner_hello_api_runners_post,
)
from mycelium_backend_client.api.sessions import (
    drain_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_get,
    report_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_outcomes_post,
)
from mycelium_backend_client.models import RunnerHello

#: Every route module the CLI sends through ``sent_unparsed``.
ROUTES = [
    get_memory_api_rooms_room_name_memory_key_get,
    confirm_delivery_api_rooms_room_name_await_confirm_post,
    get_runner_api_runners_runner_id_get,
    next_job_api_runners_runner_id_jobs_next_get,
    report_job_api_runners_runner_id_jobs_job_id_patch,
    runner_hello_api_runners_post,
    drain_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_get,
    report_herdr_wakes_api_rooms_room_name_sessions_herdr_wakes_outcomes_post,
]


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.__name__.rsplit(".", 1)[-1])
def test_each_route_it_sends_still_has_its_request_builder(route) -> None:
    assert callable(getattr(route, "_get_kwargs", None)), (
        f"{route.__name__} has no _get_kwargs: openapi-python-client changed it, and "
        "mycelium.client.sent_unparsed needs another way to build the request"
    )


def test_it_sends_the_routes_request_and_hands_back_the_answer_unparsed() -> None:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"not": "a RunnerRead"})

    client = Client(base_url="http://hub", httpx_args={"transport": httpx.MockTransport(answer)})
    resp = sent_unparsed(
        runner_hello_api_runners_post, client, body=RunnerHello(id="r1", label="r1")
    )
    assert (sent[0].method, sent[0].url.path) == ("POST", "/api/runners")
    assert json.loads(sent[0].content)["id"] == "r1"
    assert resp.status_code == 200
    assert resp.json() == {"not": "a RunnerRead"}
