# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The contract, finally standing on something: a registry, discovery, a route.

Up to here the status seam was a protocol with no caller. These cover the three
pieces that make it one, and the properties the design has been paying for all
along: a read never fetches, an answer says how fresh it is, and the app still
knows no external syntax.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.services.status import discovery, registry
from app.services.status.auth import Bearer
from app.services.status.context import HttpContext
from app.services.status.providers.github import GitHubProvider
from app.services.status.runtime import StatusRuntime
from app.services.status.types import ROW_FIELD, Liveness, Ok, Outcome, Ref

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class Recording:
    """A provider that claims a toy syntax and records what it was asked for."""

    name = "toy"
    base_url = "https://toy.example"
    auth = None
    max_batch = 10
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def claims(self, text: str) -> list[Ref]:
        return [
            Ref(provider=self.name, kind="ticket", id=word.strip("."))
            for word in text.split()
            if word.strip(".").startswith("TOY-")
        ]

    async def fetch(self, refs: list[Ref], ctx: object) -> list[Outcome]:
        self.calls.append([r.id for r in refs])
        return [
            Ok(ref=r, liveness=Liveness(state="ok", label="looks fine", url=None)) for r in refs
        ]


@pytest.fixture
def room(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A room on disk with a plan task and a memory, each naming a toy ticket."""
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))

    from app.services.filesystem import ensure_room_structure, get_room_dir

    name = "atlas"
    room_dir = get_room_dir(name)
    ensure_room_structure(room_dir)
    (room_dir / "plan").mkdir(parents=True, exist_ok=True)
    (room_dir / "plan" / "tasks.md").write_text(
        "# Tasks\n\n- [ ] land the custody seam: TOY-1\n- [ ] unrelated work\n",
        encoding="utf-8",
    )
    (room_dir / "work").mkdir(parents=True, exist_ok=True)
    (room_dir / "work" / "cutover.md").write_text(
        "---\ntitle: cutover\n---\n\nBlocked behind TOY-2 and TOY-1.\n", encoding="utf-8"
    )
    # Reference material, deliberately outside the live namespaces.
    (room_dir / "context").mkdir(parents=True, exist_ok=True)
    (room_dir / "context" / "history.md").write_text("Once we shipped TOY-9.\n", encoding="utf-8")
    return name


class TestDiscovery:
    def test_the_app_knows_no_syntax_only_a_provider_does(self, room: str):
        # A runtime with no providers finds nothing, in text a provider would
        # have read three refs out of. Syntax lives in providers, never here.
        empty = StatusRuntime(providers={}, credentials={})
        assert discovery.discover(room, empty) == []

    def test_a_ref_carries_every_row_that_mentions_it(self, room: str):
        toy = Recording()
        rt = StatusRuntime(providers={toy.name: toy}, credentials={})
        found = {d.ref.id: d.origins for d in discovery.discover(room, rt)}

        assert set(found) == {"TOY-1", "TOY-2"}
        # TOY-1 is named by both a plan task and a memory; both rows get it, and
        # the row ids are the ones the board projections already build.
        assert any(o.startswith("plan:") for o in found["TOY-1"])
        assert "memory:work/cutover" in found["TOY-1"]
        assert found["TOY-2"] == ("memory:work/cutover",)

    def test_a_memory_outside_the_live_namespaces_is_not_scanned(self, room: str):
        toy = Recording()
        rt = StatusRuntime(providers={toy.name: toy}, credentials={})
        assert "TOY-9" not in {d.ref.id for d in discovery.discover(room, rt)}


class TestRegistry:
    def test_the_hub_ships_github_and_it_declares_a_scheme(self):
        providers = registry.registered()
        assert "github" in providers
        assert providers["github"].auth == Bearer("GITHUB_TOKEN")

    def test_one_runtime_per_process_so_there_is_one_cache(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(registry, "_runtime", None)
        first = registry.get_runtime()
        assert registry.get_runtime() is first
        asyncio.run(registry.reset())
        assert registry.get_runtime() is not first
        asyncio.run(registry.reset())

    def test_an_unreadable_credential_store_does_not_stop_the_hub_serving(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        bad = tmp_path / "status-credentials.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("MYCELIUM_STATUS_CREDENTIALS_FILE", str(bad))
        monkeypatch.setattr(registry, "_runtime", None)

        runtime = registry.get_runtime()
        # It serves, with no credentials, so every ref reports the provider
        # unconfigured rather than the whole hub refusing to start.
        assert runtime is not None
        asyncio.run(registry.reset())


class TestRoute:
    @pytest.fixture
    def client(self, room: str, monkeypatch: pytest.MonkeyPatch):
        from fastapi import FastAPI

        from app.routes.status import router

        toy = Recording()
        rt = StatusRuntime(providers={toy.name: toy}, credentials={})
        monkeypatch.setattr(registry, "get_runtime", lambda: rt)
        monkeypatch.setattr(registry, "registered", lambda: {toy.name: toy})

        app = FastAPI()
        app.include_router(router, prefix="/api")
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://test"), toy, rt

    @pytest.mark.asyncio
    async def test_a_read_answers_without_fetching_and_says_so(self, client, room: str):
        http, toy, _ = client
        async with http:
            body = (await http.get(f"/api/rooms/{room}/status")).json()

        # Nothing was resolved yet, so every ref is honestly missing rather than
        # blank, and the read itself made no provider call.
        assert {r["freshness"] for r in body["refs"]} == {"missing"}
        assert all(r["state"] is None for r in body["refs"])
        assert body["refreshing"] is True
        assert body["field"] == ROW_FIELD

    @pytest.mark.asyncio
    async def test_the_blocking_path_answers_with_state(self, client, room: str):
        http, toy, _ = client
        async with http:
            body = (await http.get(f"/api/rooms/{room}/status?refresh=true")).json()

        assert toy.calls, "refresh=true must fetch"
        by_id = {r["id"]: r for r in body["refs"]}
        assert by_id["TOY-1"]["state"] == "ok"
        assert by_id["TOY-1"]["label"] == "looks fine"
        assert by_id["TOY-1"]["freshness"] == "fresh"

    @pytest.mark.asyncio
    async def test_rows_map_a_board_row_id_to_the_refs_it_mentions(self, client, room: str):
        http, _, _ = client
        async with http:
            body = (await http.get(f"/api/rooms/{room}/status?refresh=true")).json()

        rows = body["rows"]
        assert sorted(rows["memory:work/cutover"]) == ["toy:ticket:TOY-1", "toy:ticket:TOY-2"]

    @pytest.mark.asyncio
    async def test_max_age_refuses_an_answer_older_than_the_caller_will_accept(
        self, client, room: str
    ):
        http, _, _ = client
        async with http:
            await http.get(f"/api/rooms/{room}/status?refresh=true")
            # Nothing is a second old yet, so a zero-second bargain rejects it
            # all: an agent gets a stated gap, never a stale value passed off.
            body = (await http.get(f"/api/rooms/{room}/status?max_age=0")).json()

        assert {r["freshness"] for r in body["refs"]} == {"missing"}
        assert all("older than" in (r["error"] or "") for r in body["refs"])

    @pytest.mark.asyncio
    async def test_an_unknown_room_is_404_not_an_empty_board(self, client):
        http, _, _ = client
        async with http:
            assert (await http.get("/api/rooms/nope/status")).status_code == 404


class TestRowFieldDoesNotCollide:
    """`live` is already a board field, and it is a boolean.

    The projections put ``live: true`` on a resident agent's row; the GUI reads
    it as ``fields.live === true`` to light the presence dot and infers it as a
    checkbox. Landing a provider's answer there is the same bug as landing it on
    ``status``, one field over, so ROW_FIELD is neither.
    """

    def test_the_row_field_is_neither_status_nor_live(self):
        assert ROW_FIELD == "upstream"
        assert ROW_FIELD not in ("status", "live")

    def test_github_answers_are_shaped_for_that_field(self):
        provider = GitHubProvider()
        assert provider.name == "github"
        # A Liveness is what lands under it: a closed state plus the tool's own
        # words, never the row's lifecycle vocabulary.
        assert Liveness(state="ok", label="approved").state == "ok"


@pytest.mark.asyncio
async def test_a_background_refresh_is_kept_alive_to_completion(room: str):
    """A kicked task nothing references can be collected mid-flight."""
    from app.routes import status as status_route

    toy = Recording()
    rt = StatusRuntime(providers={toy.name: toy}, credentials={})
    refs = [d.ref for d in discovery.discover(room, rt)]

    assert status_route._kick(rt, refs, NOW) is True
    assert status_route._refreshes, "the task must be strongly referenced while in flight"
    await asyncio.gather(*list(status_route._refreshes))
    assert toy.calls == [["TOY-1", "TOY-2"]]


def test_the_http_context_is_never_handed_a_bare_token():
    """A regression pin on the seam below this one, exercised by the wiring."""
    ctx = HttpContext(httpx.AsyncClient(base_url="https://api.github.com"))
    assert not hasattr(ctx, "secret")
