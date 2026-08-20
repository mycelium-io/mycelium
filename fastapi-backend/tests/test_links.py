# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Memory linking — parsing, the link index, resolution, and transclusion."""

import pytest

from app.services import links
from app.services.filesystem import get_room_dir, write_memory_file


def _write(room: str, key: str, body: str, **meta) -> None:
    """Write a memory file and refresh its link-index line."""
    write_memory_file(get_room_dir(room), key, body, created_by="tester", extra_meta=meta or None)
    links.upsert(room, key, meta, body)


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parses_all_four_link_forms():
    body = (
        "See [[decisions/db]] and myc://context/stack.\n"
        "Also [the call](myc://decisions/db) plus ![[glossary/term]].\n"
    )
    found = links.parse_body_links(body)
    kinds = {(link.kind, link.target) for link in found}

    assert ("wikilink", "decisions/db") in kinds
    assert ("uri", "context/stack") in kinds
    assert ("uri", "decisions/db") in kinds
    assert ("transclusion", "glossary/term") in kinds


def test_wikilink_carries_anchor_and_label():
    (link,) = links.parse_body_links("[[decisions/db#Trade Offs|why we chose it]]")

    assert link.target == "decisions/db"
    assert link.anchor == "trade-offs"
    assert link.label == "why we chose it"


def test_transclusion_is_not_also_a_wikilink():
    found = links.parse_body_links("![[glossary/term]]")

    assert [link.kind for link in found] == ["transclusion"]


def test_uri_inside_a_wikilink_is_one_edge():
    found = links.parse_body_links("[[myc://decisions/db]]")

    assert len(found) == 1
    assert found[0].target == "decisions/db"


def test_skill_directive_is_not_a_link():
    """`[[mycelium: …]]` is the agent skill's directive syntax, not a wikilink."""
    assert links.parse_body_links("[[mycelium: confidence=0.85 stance=accept]]") == []


def test_links_inside_code_are_not_edges():
    body = "Write `[[decisions/db]]` to link.\n\n```\n[[context/stack]]\n```\n"

    assert links.parse_body_links(body) == []


def test_key_normalization_collapses_equivalent_targets():
    assert links.normalize_key("myc://decisions/db.md") == "decisions/db"
    assert links.normalize_key("/decisions/db") == "decisions/db"
    assert links.normalize_key("./decisions/db") == "decisions/db"


def test_cross_room_link_parses_but_is_rejected():
    (link,) = links.parse_body_links("myc://rooms/other/decisions/db")

    assert link.error == links.ERR_CROSS_ROOM


def test_frontmatter_relations_become_typed_edges():
    meta = {"supersedes": "decisions/db-v1", "depends-on": ["context/stack", "procedures/deploy"]}
    found = links.parse_relation_links(meta)

    assert {(link.relation, link.target) for link in found} == {
        ("supersedes", "decisions/db-v1"),
        ("depends-on", "context/stack"),
        ("depends-on", "procedures/deploy"),
    }
    assert all(link.kind == links.KIND_RELATION for link in found)


# ── Index + resolution ───────────────────────────────────────────────────────


def test_outbound_resolves_against_the_room():
    _write("r", "context/stack", "The stack.")
    _write("r", "decisions/db", "Because of [[context/stack]] and [[context/missing]].")

    by_target = {link.target: link for link in links.outbound("r", "decisions/db")}

    assert by_target["context/stack"].resolved is True
    assert by_target["context/missing"].resolved is False
    assert by_target["context/missing"].error == links.ERR_NOT_FOUND


def test_backlinks_report_who_points_here():
    _write("r", "context/stack", "The stack.")
    _write("r", "decisions/db", "See [[context/stack]].")
    _write("r", "procedures/deploy", "Per [[context/stack]].")

    sources = {link.source for link in links.backlinks("r", "context/stack")}

    assert sources == {"decisions/db", "procedures/deploy"}


def test_backlinks_are_empty_for_an_unreferenced_memory():
    _write("r", "context/stack", "The stack.")

    assert links.backlinks("r", "context/stack") == []


def test_anchor_must_exist_on_the_target():
    _write("r", "context/stack", "## Vector store\nfastembed.\n")
    _write("r", "a", "[[context/stack#vector-store]]")
    _write("r", "b", "[[context/stack#nope]]")

    assert links.outbound("r", "a")[0].resolved is True
    assert links.outbound("r", "b")[0].error == links.ERR_NO_ANCHOR


def test_delete_removes_the_index_line():
    _write("r", "context/stack", "The stack.")
    assert links.remove("r", "context/stack") is True

    assert links.load_index("r") == []


def test_rebuild_reconstructs_the_index_from_markdown():
    _write("r", "context/stack", "The stack.")
    _write("r", "decisions/db", "See [[context/stack]].")
    links.write_index("r", [])

    assert links.rebuild("r") == 2
    assert {link.source for link in links.backlinks("r", "context/stack")} == {"decisions/db"}


def test_integrity_reports_broken_links_and_graph_roles():
    # decisions/db → context/stack (resolved) and → gone (broken)
    # context/stack: inbound=1, outbound=0 → leaf
    # decisions/db:  inbound=0, outbound=2 → root  (has outbound intent)
    _write("r", "context/stack", "The stack.")
    _write("r", "decisions/db", "See [[context/stack]] and [[gone]].")

    report = links.integrity("r")

    assert [b["target"] for b in report["broken"]] == ["gone"]
    assert report["orphans"] == []  # no memory is fully isolated
    assert report["roots"] == ["decisions/db"]  # inbound=0, has outbound
    assert report["leaves"] == ["context/stack"]  # inbound=1, outbound=0
    assert report["total_memories"] == 2


def test_integrity_reports_true_orphan():
    # A memory with no links at all — no inbound, no outbound.
    _write("r", "context/stack", "See [[decisions/db]].")
    _write("r", "decisions/db", "The decision.")
    _write("r", "status/lonely", "Just sitting here.")

    report = links.integrity("r")

    assert report["orphans"] == ["status/lonely"]
    assert report["roots"] == ["context/stack"]
    assert report["leaves"] == ["decisions/db"]


def test_graph_counts_both_directions():
    _write("r", "context/stack", "The stack.")
    _write("r", "decisions/db", "See [[context/stack]].")

    nodes = {node["key"]: node for node in links.graph("r")["nodes"]}

    assert nodes["decisions/db"]["outbound"] == 1
    assert nodes["context/stack"]["inbound"] == 1


# ── Transclusion ─────────────────────────────────────────────────────────────


def test_expansion_requires_the_expandable_flag():
    _write("r", "glossary/term", "A definition.", expandable=True)
    _write("r", "context/plain", "Not expandable.")
    _write("r", "reader", "![[glossary/term]] and ![[context/plain]]")

    result = links.expand("r", "reader")

    assert "A definition." in result["rendered"]
    # The refused embed is left verbatim, never blanked.
    assert "![[context/plain]]" in result["rendered"]
    errors = {e["target"]: e["error"] for e in result["expansions"]}
    assert errors["context/plain"] == links.ERR_NOT_EXPANDABLE
    assert errors["glossary/term"] is None


def test_expansion_pulls_only_the_anchored_section():
    _write(
        "r",
        "glossary/stack",
        "## Vector store\nfastembed, 384-dim.\n\n## Messaging\nSLIM.\n",
        expandable=True,
    )
    _write("r", "reader", "![[glossary/stack#vector-store]]")

    rendered = links.expand("r", "reader")["rendered"]

    assert "fastembed, 384-dim." in rendered
    assert "SLIM." not in rendered


def test_expansion_does_not_recurse():
    """Depth 1: a marker inside expanded text stays literal, so cycles can't form."""
    _write("r", "glossary/a", "A, see ![[glossary/b]]", expandable=True)
    _write("r", "glossary/b", "B", expandable=True)
    _write("r", "reader", "![[glossary/a]]")

    rendered = links.expand("r", "reader")["rendered"]

    assert "A, see ![[glossary/b]]" in rendered
    assert "\nB" not in rendered


def test_expansion_of_a_missing_target_is_reported_not_blanked():
    _write("r", "reader", "![[glossary/gone]]")

    result = links.expand("r", "reader")

    assert "![[glossary/gone]]" in result["rendered"]
    assert result["expansions"][0]["error"] == links.ERR_NOT_FOUND


def test_body_with_no_markers_renders_unchanged():
    _write("r", "reader", "Just prose.")

    result = links.expand("r", "reader")

    assert result["rendered"] == "Just prose."
    assert result["expansions"] == []


def test_expand_reports_a_missing_memory():
    assert links.expand("r", "nope")["found"] is False


def test_expansion_skips_a_marker_quoted_as_a_code_example():
    """Backtick-quoted markers are not expanded; ``expand`` must skip them like ``parse_body_links``."""
    _write(
        "r",
        "glossary/self",
        "Definition. Other pages embed this with `![[glossary/self]]`.",
        expandable=True,
    )
    _write("r", "reader", "![[glossary/self]]")

    result = links.expand("r", "reader")

    assert result["rendered"].count("Definition.") == 1
    assert "`![[glossary/self]]`" in result["rendered"]
    assert result["expansions"] == [
        {
            "target": "glossary/self",
            "anchor": None,
            "raw": "![[glossary/self]]",
            "expanded": True,
            "error": None,
        }
    ]


# ── Empty graph / missing index ──────────────────────────────────────────────


def test_a_room_that_never_linked_has_an_empty_graph():
    _write("r", "context/stack", "Plain prose, no links at all.")

    assert links.graph("r")["edges"] == []
    assert links.integrity("r")["broken"] == []


def test_missing_index_resolves_to_empty_rather_than_raising():
    get_room_dir("fresh")

    assert links.load_index("fresh") == []
    assert links.outbound("fresh", "anything") == []
    assert links.backlinks("fresh", "anything") == []


@pytest.mark.parametrize("body", ["[[]]", "[[   ]]", "![[]]", "myc://"])
def test_degenerate_link_syntax_is_ignored(body):
    assert links.parse_body_links(body) == []
