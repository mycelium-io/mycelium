# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Tests for the plan/ namespace + projection API."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import plan as plan_service
from app.services.filesystem import get_room_dir


class TestParseTasks:
    def test_open_and_done(self):
        body = (
            "# Sprint\n\n"
            "- [ ] write the parser\n"
            "- [x] sketch the API\n"
            "  - [ ] nested still counts\n"
            "not a task line\n"
        )
        tasks = plan_service.parse_tasks("sprint", body)
        assert [(t.line, t.text, t.done) for t in tasks] == [
            (3, "write the parser", False),
            (4, "sketch the API", True),
            (5, "nested still counts", False),
        ]
        assert tasks[0].id == "sprint:3"

    def test_no_tasks(self):
        assert plan_service.parse_tasks("foo", "just prose, no checkboxes") == []


class TestAddAndToggle:
    def test_add_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        t = plan_service.add_task("room-a", "first task")
        assert t.done is False
        assert t.text == "first task"
        path = Path(tmp_path) / "rooms" / "room-a" / "plan" / "tasks.md"
        assert path.exists()
        assert "- [ ] first task" in path.read_text()

    def test_add_appends(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        plan_service.add_task("room-b", "one")
        plan_service.add_task("room-b", "two")
        body = (Path(tmp_path) / "rooms" / "room-b" / "plan" / "tasks.md").read_text()
        assert body.count("- [ ]") == 2

    def test_toggle_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        t = plan_service.add_task("room-c", "do the thing")
        flipped = plan_service.toggle_task("room-c", t.id)
        assert flipped.done is True
        # Re-parse and confirm persistence
        _, tasks = plan_service.load_plan("room-c")
        assert tasks[0].done is True

        unflipped = plan_service.toggle_task("room-c", t.id, done=False)
        assert unflipped.done is False

    def test_toggle_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        with pytest.raises(KeyError):
            plan_service.toggle_task("nope", "missing:1")


class TestWritePlanFile:
    """write_plan_file / read_plan_file — the whole-body writer the compiler uses."""

    def test_write_and_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        body = "# Launch plan\n\n- [ ] write the parser\n- [x] sketch the API\n"
        plan_service.write_plan_file("room-w", body)

        assert plan_service.read_plan_file("room-w") == body.rstrip("\n")
        # The body must still parse as a plan: load_plan strips the frontmatter
        # write_memory_file adds, and parse_tasks sees both checkbox states.
        _, tasks = plan_service.load_plan("room-w")
        assert [(t.text, t.done) for t in tasks] == [
            ("write the parser", False),
            ("sketch the API", True),
        ]

    def test_write_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        plan_service.write_plan_file("room-o", "# A\n\n- [ ] one\n")
        plan_service.write_plan_file("room-o", "# B\n\n- [ ] two\n")
        body = plan_service.read_plan_file("room-o")
        assert body is not None
        assert "one" not in body
        assert "two" in body

    def test_read_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        assert plan_service.read_plan_file("never-created") is None

    def test_toggle_on_compiler_written_file(self, tmp_path, monkeypatch):
        """A compiler-written file carries frontmatter; toggle_task must still work."""
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        plan_service.write_plan_file("room-t", "# Plan\n\n- [ ] do the thing\n")
        _, tasks = plan_service.load_plan("room-t")
        flipped = plan_service.toggle_task("room-t", tasks[0].id)
        assert flipped.done is True
        _, reloaded = plan_service.load_plan("room-t")
        assert reloaded[0].done is True


class TestOpenTaskSummary:
    def test_summary_groups_and_caps(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        for i in range(3):
            plan_service.add_task("r", f"task {i}")
        # complete one
        _, tasks = plan_service.load_plan("r")
        plan_service.toggle_task("r", tasks[0].id, done=True)

        summary = plan_service.open_task_summary("r")
        assert summary is not None
        assert "Open tasks (2)" in summary
        assert "task 1" in summary and "task 2" in summary

    def test_summary_none_when_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        assert plan_service.open_task_summary("empty") is None


class TestAgentContext:
    def test_none_when_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        assert plan_service.agent_context("empty") is None

    def test_includes_title_and_open_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        plan_service.set_title("r", "Ship the Q3 release")
        plan_service.add_task("r", "write the parser")
        plan_service.add_task("r", "ship the demo")
        ctx = plan_service.agent_context("r")
        assert ctx is not None
        assert "Plan: Ship the Q3 release" in ctx
        assert "Open tasks (2)" in ctx
        assert "write the parser" in ctx

    def test_title_only_no_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.config.settings.MYCELIUM_DATA_DIR", str(tmp_path))
        plan_service.set_title("r", "Just a title")
        ctx = plan_service.agent_context("r")
        assert ctx is not None
        assert "Plan: Just a title" in ctx


@pytest.mark.asyncio
class TestPlanRoutes:
    async def test_get_plan_empty(self, client: AsyncClient):
        resp = await client.get("/api/rooms/no-such-room/plan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
        assert data["tasks"] == []

    async def test_add_get_toggle(self, client: AsyncClient):
        room = "plan-rt"
        await client.post("/api/rooms", json={"name": room})

        # Add a task
        resp = await client.post(
            f"/api/rooms/{room}/plan/tasks",
            json={"text": "ship the feature"},
        )
        assert resp.status_code == 200
        task = resp.json()
        assert task["done"] is False

        # GET projection sees it
        resp = await client.get(f"/api/rooms/{room}/plan")
        data = resp.json()
        assert data["open_count"] == 1
        assert data["files"][0]["slug"] == "tasks"

        # Toggle done
        resp = await client.post(
            f"/api/rooms/{room}/plan/tasks/{task['id']}/toggle",
            json={"done": True},
        )
        assert resp.status_code == 200
        assert resp.json()["done"] is True

        # Re-read
        resp = await client.get(f"/api/rooms/{room}/plan")
        data = resp.json()
        assert data["open_count"] == 0
        assert data["done_count"] == 1

    async def test_title_roundtrip(self, client: AsyncClient):
        room = "plan-title"
        await client.post("/api/rooms", json={"name": room})

        # No title initially
        resp = await client.get(f"/api/rooms/{room}/plan")
        assert resp.json()["title"] is None

        # Set it
        resp = await client.put(
            f"/api/rooms/{room}/plan/title",
            json={"text": "Plan the Q3 sprint priorities"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Plan the Q3 sprint priorities"

        # Read back via GET /plan
        resp = await client.get(f"/api/rooms/{room}/plan")
        assert resp.json()["title"] == "Plan the Q3 sprint priorities"

        # Clear it
        resp = await client.put(
            f"/api/rooms/{room}/plan/title",
            json={"text": ""},
        )
        assert resp.status_code == 200
        resp = await client.get(f"/api/rooms/{room}/plan")
        assert resp.json()["title"] is None

    async def test_room_creation_includes_plan_dir(self, client: AsyncClient):
        await client.post("/api/rooms", json={"name": "with-plan"})
        plan_dir = get_room_dir("with-plan") / "plan"
        assert plan_dir.exists() and plan_dir.is_dir()

    async def test_agent_context_endpoint(self, client: AsyncClient):
        room = "plan-agentctx"
        await client.post("/api/rooms", json={"name": room})

        # Empty room → context is null, generated_at still present
        resp = await client.get(f"/api/rooms/{room}/agent-context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["context"] is None
        assert data["generated_at"]
        assert data["room"] == room

        # Add a task → context surfaces it
        await client.post(f"/api/rooms/{room}/plan/tasks", json={"text": "do the thing"})
        resp = await client.get(f"/api/rooms/{room}/agent-context", params={"handle": "alpha"})
        data = resp.json()
        assert data["handle"] == "alpha"
        assert "do the thing" in data["context"]
        assert "Open tasks (1)" in data["context"]
