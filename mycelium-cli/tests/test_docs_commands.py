# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Unit tests for ``mycelium docs``.

The markdown tree is organised into subdirectories (``concepts/``, ``guides/``,
``reference/``) so it reads well browsed on GitHub, while a topic stays the bare
stem on the command line. These pin that seam: every section ``--list`` and
``--full`` advertise must resolve, and ``mycelium docs <topic>`` must find a file
wherever the tree currently keeps it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mycelium.commands import docs as docs_cmd
from mycelium.commands.docs import SECTIONS, _get_docs_root, _resolve_topic

runner = CliRunner()

DOCS_ROOT = _get_docs_root()


@pytest.mark.parametrize("topic", [stem for stem, _ in SECTIONS])
def test_every_advertised_section_resolves(topic: str) -> None:
    assert _resolve_topic(DOCS_ROOT, topic) is not None, (
        f"'mycelium docs {topic}' is listed but no markdown file backs it"
    )


@pytest.mark.parametrize("topic", ["rooms", "quickstart", "architecture", "troubleshooting"])
def test_bare_topic_reads_the_file(topic: str) -> None:
    """A topic that lives in a subdirectory is still addressed by stem alone."""
    result = runner.invoke(docs_cmd.app, [topic])
    assert result.exit_code == 0
    assert result.output.strip()


def test_topic_resolves_from_a_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "widgets.md").write_text("# Widgets\n")
    assert _resolve_topic(tmp_path, "widgets") == tmp_path / "concepts" / "widgets.md"
    assert _resolve_topic(tmp_path, "absent") is None


def test_top_level_file_wins_over_a_subdirectory_copy(tmp_path: Path) -> None:
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "dupe.md").write_text("# From guides\n")
    (tmp_path / "dupe.md").write_text("# From root\n")
    assert _resolve_topic(tmp_path, "dupe") == tmp_path / "dupe.md"


def test_unknown_topic_exits_nonzero() -> None:
    assert runner.invoke(docs_cmd.app, ["no-such-topic"]).exit_code == 1


def test_full_dump_covers_every_section() -> None:
    output = runner.invoke(docs_cmd.app, ["--full"]).output
    for topic, _ in SECTIONS:
        path = _resolve_topic(DOCS_ROOT, topic)
        assert path is not None
        first_line = path.read_text().split("\n", 1)[0]
        assert first_line in output, f"--full omitted {topic}"
