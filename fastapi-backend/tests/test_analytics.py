# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Usage events (app/services/analytics.py): recorded on the hub, forwarded only with consent.

No network, no backend process, no SLIM node.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.routes.memory import _is_agent_manifest, _manifest_adapter
from app.services import analytics as usage


@pytest.fixture(autouse=True)
def hub(tmp_path, monkeypatch):
    """A hub with its own data dir, not sharing usage, and no install id."""
    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TELEMETRY_SEND_PRODUCT_ANALYTICS", False)
    monkeypatch.setattr(settings, "TELEMETRY_ANALYTICS_DESTINATION", "")
    monkeypatch.setattr(settings, "TELEMETRY_INSTALL_ID", "")
    return tmp_path


@pytest.fixture
def posted(monkeypatch):
    """What would have been POSTed, with forwarding run inline instead of on a thread."""
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(usage, "_post", lambda url, payload: sent.append((url, payload)))

    class InlineThread:
        def __init__(self, target, args, daemon):
            self._run = lambda: target(*args)

        def start(self):
            self._run()

    monkeypatch.setattr(usage.threading, "Thread", InlineThread)
    return sent


def logged(hub) -> list[dict]:
    path = hub / "usage" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestRecordedOnTheHub:
    def test_every_event_lands_in_the_hubs_log(self, hub):
        usage.flow_completed("review", "resolved", 4)
        [event] = logged(hub)
        assert event["event"] == "mycelium.flow_completed"
        assert event["flow"] == "review"
        assert event["hub_id"]
        assert event["release"]

    def test_prohibited_fields_never_reach_the_log(self, hub):
        usage.record(
            "mycelium.task_filed", room="atlas", handle="avery", title="Fix it", kind="action"
        )
        [event] = logged(hub)
        assert not set(event) & usage.PROHIBITED_FIELDS
        assert event["kind"] == "action"

    def test_the_prohibited_set_covers_names_rooms_and_content(self):
        assert {
            "handle",
            "room",
            "title",
            "key",
            "content",
            "prompt",
            "reply",
            "email",
            "hostname",
        } <= (usage.PROHIBITED_FIELDS)

    def test_a_rooms_own_flow_is_counted_as_custom(self, hub):
        usage.flow_completed("our-secret-release-train", "resolved", 3)
        assert logged(hub)[0]["flow"] == "custom"

    def test_finished_work_carries_a_running_count(self, hub):
        usage.record("mycelium.task_filed", kind="action")
        usage.negotiation_completed("converged", 3)
        usage.flow_completed("swarm", "resolved", 5)
        counts = [e.get("work_count") for e in logged(hub)]
        assert counts == [None, 1, 2]

    def test_the_hub_keeps_one_id(self, hub):
        first = usage.hub_id()
        assert usage.hub_id() == first
        assert (hub / "usage" / "hub_id").read_text() == first

    def test_an_install_id_from_the_cli_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "TELEMETRY_INSTALL_ID", "from-install")
        assert usage.hub_id() == "from-install"

    def test_recording_never_raises(self, monkeypatch):
        monkeypatch.setattr(
            usage, "_append", lambda payload: (_ for _ in ()).throw(OSError("disk full"))
        )
        assert usage.record("mycelium.hub_started", mode="desktop") is None


class TestForwardedOnlyWithConsent:
    def test_nothing_leaves_without_consent(self, posted, monkeypatch):
        monkeypatch.setattr(
            settings, "TELEMETRY_ANALYTICS_DESTINATION", "https://usage.example.com"
        )
        usage.hub_started()
        assert posted == []

    def test_nothing_leaves_without_a_destination(self, posted, monkeypatch):
        monkeypatch.setattr(settings, "TELEMETRY_SEND_PRODUCT_ANALYTICS", True)
        usage.hub_started()
        assert posted == []

    def test_with_consent_and_a_destination_each_event_is_sent(self, posted, monkeypatch):
        monkeypatch.setattr(settings, "TELEMETRY_SEND_PRODUCT_ANALYTICS", True)
        monkeypatch.setattr(
            settings, "TELEMETRY_ANALYTICS_DESTINATION", "https://usage.example.com"
        )
        usage.agent_joined("claude_code")
        [(url, payload)] = posted
        assert url == "https://usage.example.com"
        assert payload["event"] == "mycelium.agent_joined"
        assert payload["adapter"] == "claude_code"

    @pytest.mark.parametrize(
        ("url", "allowed"),
        [
            ("https://usage.example.com", True),
            ("http://localhost:3100/loki/api/v1/push", True),
            ("http://127.0.0.1:9000", True),
            ("http://usage.example.com", False),
            ("http://evil.example/localhost", False),
        ],
    )
    def test_plain_http_only_to_this_machine(self, monkeypatch, url, allowed):
        monkeypatch.setattr(settings, "TELEMETRY_SEND_PRODUCT_ANALYTICS", True)
        monkeypatch.setattr(settings, "TELEMETRY_ANALYTICS_DESTINATION", url)
        assert (usage.destination() == url) is allowed


class TestTheBoardAsUsage:
    def test_a_filed_task_is_counted_by_kind_and_who_filed_it(self, hub):
        usage.on_notice(
            "atlas",
            {
                "subkind": "filed",
                "key": "work/fix-login",
                "kind": "action",
                "by": "avery",
                "for": "codex",
            },
        )
        [event] = logged(hub)
        assert event["event"] == "mycelium.task_filed"
        assert event == event | {"kind": "action", "by": "person", "assigned": True}
        assert "avery" not in json.dumps(event)
        assert "fix-login" not in json.dumps(event)

    def test_a_resolved_task_is_finished_work(self, hub):
        usage.on_notice("atlas", {"subkind": "resolved", "key": "work/fix-login", "by": "codex"})
        [event] = logged(hub)
        assert event["event"] == "mycelium.task_resolved"
        assert event["kind"] == "work"
        assert event["work_count"] == 1

    def test_other_board_moves_are_not_usage(self, hub):
        usage.on_notice("atlas", {"subkind": "claimed", "key": "work/fix-login", "by": "codex"})
        assert not (hub / "usage" / "events.jsonl").exists()


class TestKpis:
    def test_what_the_hub_adds_up_to(self, hub):
        usage.hub_started()
        usage.record("mycelium.task_filed", kind="action", by="person", assigned=True)
        usage.record("mycelium.task_filed", kind="action", by="agent", assigned=False)
        usage.record("mycelium.task_resolved", kind="action", by="agent", hours_open=2.0)
        usage.record("mycelium.task_resolved", kind="action", by="agent", hours_open=6.0)
        usage.flow_completed("review", "resolved", 4)
        usage.flow_completed("review", "rejected", 9)
        usage.negotiation_completed("converged", 3)
        usage.agent_joined("claude_code")

        k = usage.kpis(7)
        assert k["tasks"] == {
            "filed": 2,
            "resolved": 2,
            "filed_by": {"person": 1, "agent": 1},
            "median_hours_open": 4.0,
            "median_hours_open_by": {"agent": 4.0},
        }
        assert k["flows"] == {"review": {"resolved": 1, "rejected": 1}}
        assert k["negotiations"] == {"converged": 1}
        assert k["agents_joined"] == {"claude_code": 1}
        assert k["work_total"] == 5
        assert k["active_days"] == 1
        assert len(k["daily"]) == 7
        assert k["daily"][-1]["filed"] == 2
        assert k["first_value_hours"] is not None
        assert k["sharing"] is False

    def test_the_window_leaves_older_events_out(self, hub):
        old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        (hub / "usage").mkdir(parents=True)
        (hub / "usage" / "events.jsonl").write_text(
            json.dumps({"event": "mycelium.task_filed", "ts": old, "kind": "action"}) + "\n"
        )
        assert usage.kpis(30)["tasks"]["filed"] == 0
        assert usage.kpis(60)["tasks"]["filed"] == 1

    def test_an_empty_hub_has_nothing_to_report(self):
        k = usage.kpis(30)
        assert k["tasks"]["filed"] == 0
        assert k["first_value_hours"] is None


class TestAgentManifests:
    @pytest.mark.parametrize(
        ("key", "manifest"),
        [
            ("agents/codex", True),
            ("agents/codex/notes", False),
            ("work/agents", False),
            ("agents/", False),
        ],
    )
    def test_only_the_manifest_itself_is_an_agent_joining(self, key, manifest):
        assert _is_agent_manifest(key) is manifest

    def test_the_adapter_is_read_from_a_value_or_its_yaml(self):
        assert _manifest_adapter({"adapter": "cursor"}, "") == "cursor"
        assert (
            _manifest_adapter({"text": "adapter: claude_code\nrole: builder"}, "") == "claude_code"
        )
        assert _manifest_adapter({"text": "not: [yaml"}, "") is None
