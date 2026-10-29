# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Tests for the episode record a run writes to ``log/episodes/``."""

from pathlib import Path

import pytest

from app.services import episode_state, message_format
from app.services.message_models import Kind


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    from app.config import settings

    monkeypatch.setattr(settings, "MYCELIUM_DATA_DIR", str(tmp_path))


def _episode() -> episode_state.EpisodeState:
    episode = message_format.episode_urn("sprint", "abc123")
    topic = message_format.topic_urn("sprint")
    ep = episode_state.EpisodeState(
        episode=episode,
        topic=topic,
        parent_room="sprint",
        short_id="abc123",
        workspace_id="ws-1",
        mas_id="mas-1",
        agents=["a1", "a2"],
        engine_handle="conductor",
    )
    for kind, sender in ((Kind.intent, "conductor"), (Kind.exchange, "a1")):
        env = message_format.build_envelope(
            kind=kind,
            subkind="mission" if kind == Kind.intent else None,
            episode=episode,
            topic=topic,
            sender=sender,
        )
        ep.messages.append(message_format.envelope_to_dict(env))
    return ep


def _body(tmp_path: Path) -> str:
    return (tmp_path / "rooms" / "sprint" / "log" / "episodes" / "abc123.md").read_text()


def test_write_episode_record(tmp_path):
    episode_state.write_episode_record(_episode(), outcome="converged", metrics=None)
    body = _body(tmp_path)
    assert "urn:ioc:mycelium:episode:sprint:abc123" in body
    assert "- outcome: **converged**" in body
    assert "- participants: a1, a2" in body
    # One JSONL line per envelope: the intent and the reply.
    jsonl_lines = [ln for ln in body.splitlines() if ln.startswith('{"header"')]
    assert len(jsonl_lines) == 2


def test_episode_record_carries_a_thread_of_its_own():
    # Episode records get their own thread binding on write.
    episode_state.write_episode_record(_episode(), outcome="converged", metrics=None)

    from app.services.tasks import episode_of

    assert episode_of("sprint", "log/episodes/abc123")


def test_episode_record_renders_satisfaction(tmp_path):
    metrics = {"min_satisfaction": 0.33, "satisfaction": {"a1": 0.33, "a2": 0.8}}
    episode_state.write_episode_record(_episode(), outcome="converged", metrics=metrics)
    assert "- satisfaction: min 0.33 (least-happy of 2 members)" in _body(tmp_path)


def test_episode_record_says_where_it_sits_and_what_it_saved(tmp_path):
    ep = _episode()
    ep.within = "urn:ioc:mycelium:episode:sprint:t3"
    ep.memory = "context/decision/ship"
    episode_state.write_episode_record(ep, outcome="converged", metrics=None)
    body = _body(tmp_path)
    assert "- within: `urn:ioc:mycelium:episode:sprint:t3`" in body
    assert "- memory: `context/decision/ship`" in body
