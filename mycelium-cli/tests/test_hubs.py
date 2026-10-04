# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Every hub on this machine: where each is found, how one is told from
another, and what is worth a warning. Nothing live: docker, ps and /health
are replaced."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mycelium import hubs
from mycelium.hubs import Hub


def _health(store: str, version: str = "3.0.21", path: str = "/home/mycelium/.mycelium"):
    return {
        "service": "mycelium-backend",
        "version": version,
        "storage": {"status": "ok", "path": path, "id": store},
    }


def test_a_container_says_its_project_image_port_and_host_data_folder():
    hub = hubs._from_container(
        {
            "Id": "abc123456789ff",
            "Name": "/mycelium-concord-eval-mycelium-backend-1",
            "Config": {
                "Image": "mycelium-backend:dev",
                "Labels": {"com.docker.compose.project": "mycelium-concord-eval"},
            },
            "Mounts": [
                {
                    "Source": "/Users/julia/.mycelium-concord-eval",
                    "Destination": "/home/mycelium/.mycelium",
                },
                {"Source": "/Users/julia/patterns", "Destination": "/patterns"},
            ],
            "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}},
        }
    )
    assert hub.port == 8000
    assert hub.project == "mycelium-concord-eval"
    assert hub.data_path == "/Users/julia/.mycelium-concord-eval"
    assert hub.dev_build
    assert hub.describe() == (
        "Docker project `mycelium-concord-eval`, `mycelium-backend:dev`, "
        "data in /Users/julia/.mycelium-concord-eval, on port 8000"
    )


def test_hub_processes_are_found_once_per_port_and_never_this_one():
    ps = "\n".join(
        [
            "  101 uv run --project /src/fastapi-backend uvicorn app.main:app --host 127.0.0.1 --port 8000",
            "  102 /src/.venv/bin/python /src/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000",
            "  201 /Applications/Mycelium.app/Contents/Resources/hub/mycelium-hub --host 127.0.0.1 --port 8100",
            "  301 vim app/main.py",
            "  401 uvicorn other.main:app --port 9000",
        ]
    )
    found = hubs.process_hubs(ps)
    assert [(h.pid, h.port) for h in found] == [(101, 8000), (201, 8100)]


def test_the_hub_on_the_port_takes_what_health_says(monkeypatch: pytest.MonkeyPatch):
    docker = Hub(source="docker", port=8000, data_path="/Users/julia/.eval", image="b:dev")
    monkeypatch.setattr(hubs, "docker_hubs", lambda: [docker])
    monkeypatch.setattr(hubs, "process_hubs", lambda: [Hub(source="process", port=8001, pid=5)])
    answers = {8000: _health("eval"), 8001: _health("own", path="/Users/julia/.mycelium")}
    monkeypatch.setattr(hubs, "health", lambda port, **_: answers.get(port))
    found = hubs.find_hubs(8000)
    assert [h.source for h in found] == ["docker", "process"]
    assert hubs.at_port(found, 8000) is docker
    # A container's path inside it never stands in for the host's.
    assert docker.data_path == "/Users/julia/.eval"
    assert found[1].data_path == "/Users/julia/.mycelium"
    assert found[1].store_id == "own"


def test_something_answering_with_no_owner_found_is_still_listed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hubs, "docker_hubs", list)
    monkeypatch.setattr(hubs, "process_hubs", list)
    body = _health("x")
    body["storage"]["host_path"] = "~/.mycelium-eval"
    monkeypatch.setattr(hubs, "health", lambda port, **_: body if port == 8000 else None)
    (only,) = hubs.find_hubs(8000)
    assert only.source == "port"
    assert only.data_path == str(Path.home() / ".mycelium-eval")
    assert only.owner() == "something on port 8000"


def test_the_store_id_is_written_once_and_shared(tmp_path: Path):
    assert hubs.store_id(tmp_path, create=False) is None
    made = hubs.store_id(tmp_path)
    assert made
    assert hubs.store_id(tmp_path) == made
    assert (tmp_path / hubs.STORE_ID_FILE).read_text().strip() == made


def test_same_store_by_id_else_by_path(tmp_path: Path):
    own = hubs.store_id(tmp_path)
    assert hubs.same_store(Hub(source="port", store_id=own), tmp_path, own)
    assert hubs.same_store(Hub(source="port", store_id="other"), tmp_path, own) is False
    assert hubs.same_store(Hub(source="docker", data_path=str(tmp_path)), tmp_path, None)
    assert hubs.same_store(Hub(source="docker"), tmp_path, None) is None


@pytest.mark.parametrize(
    ("hub", "app", "why"),
    [
        (Hub(source="port", version="3.0.12"), "3.0.21", "older than this Mycelium (3.0.21)"),
        (Hub(source="port", version="3.0.21"), "3.0.21", None),
        (
            Hub(source="docker", version="3.0.21", image="mycelium-backend:dev"),
            "3.0.21",
            "a development build",
        ),
        (Hub(source="port", version="3.0.12"), "0.0.0.dev", None),
        (Hub(source="port"), "3.0.21", None),
    ],
)
def test_a_stale_hub_says_why(hub: Hub, app: str, why: str | None):
    assert hubs.stale(hub, app) == why


def test_warnings_name_a_second_hub_and_whose_store_it_is(tmp_path: Path):
    eval_stack = Hub(
        source="docker", port=8000, project="eval", image="b:latest", data_path="/elsewhere"
    )
    own = Hub(source="process", port=8001, pid=3, data_path=str(tmp_path))
    said = hubs.warnings([eval_stack, own], tmp_path, "3.0.21")
    assert said[0].startswith("2 Mycelium hubs are running")
    assert any("Docker project `eval`" in s and "/elsewhere" in s for s in said)
    assert hubs.warnings([own], tmp_path, "3.0.21") == []


def test_stopping_a_docker_hub_stops_its_whole_project(monkeypatch: pytest.MonkeyPatch):
    ran: list[list[str]] = []

    def run(argv: list[str]) -> Any:
        ran.append(argv)
        return ""

    monkeypatch.setattr(hubs, "_run", run)
    monkeypatch.setattr(hubs, "health", lambda *_a, **_k: None)
    hub = Hub(source="docker", port=8000, project="eval", project_containers=["a", "b", "c"])
    assert hubs.stop(hub) == "Docker project `eval`"
    assert ran == [["docker", "stop", "a", "b", "c"]]


def test_a_hub_with_no_known_owner_cannot_be_stopped():
    with pytest.raises(hubs.StopError, match="Can't tell what runs"):
        hubs.stop(Hub(source="port", port=8000))
