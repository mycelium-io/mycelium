# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The harness spec table is read by two consumers; these keep it honest.

``integrations/<family>/`` builds an adapter from a spec, and
``scripts/harness_conformance.py`` points a real binary at a real room from the
same spec. The failure mode worth guarding is drift between the table's claims and
the code: a family graded ``proven``/``untested`` with no integration behind it, an
argv template the runner cannot render, or a capability claim nobody can check.
"""

from __future__ import annotations

import pytest

from mycelium.integrations import get_integration, normalize_family_id
from mycelium.integrations.harness_specs import (
    HARNESS_SPECS,
    PROMPT_SLOT,
    SPECS_BY_FAMILY,
    HarnessSpec,
    get_spec,
)
from mycelium.protocol import AGENT_ADAPTERS

#: Statuses that assert an integration exists for the family.
_ADAPTER_BACKED = {"proven", "untested"}


def test_family_ids_are_unique_and_canonical() -> None:
    families = [spec.family for spec in HARNESS_SPECS]
    assert len(families) == len(set(families))
    for family in families:
        # The underscore spelling is what a manifest persists; a hyphen here would
        # silently miss every AGENT_ADAPTERS lookup.
        assert normalize_family_id(family) == family, f"{family!r} is not canonical"


@pytest.mark.parametrize("spec", HARNESS_SPECS, ids=lambda s: s.family)
def test_adapter_backed_families_have_an_integration(spec: HarnessSpec) -> None:
    """A ``proven``/``untested`` grade is a claim that code exists to back it."""
    if spec.adapter_status not in _ADAPTER_BACKED:
        return
    assert spec.family in AGENT_ADAPTERS
    assert get_integration(spec.family).name == spec.family


@pytest.mark.parametrize("spec", HARNESS_SPECS, ids=lambda s: s.family)
def test_candidates_have_no_integration_yet(spec: HarnessSpec) -> None:
    """The inverse: ``candidate`` means the adapter is the missing piece.

    If someone lands an integration without regrading the spec, the table would
    keep telling the conformance runner to skip ``participate`` for a family that
    can now reach it.
    """
    if spec.adapter_status != "candidate":
        return
    assert spec.family not in AGENT_ADAPTERS, (
        f"{spec.family!r} now has an integration; regrade it to 'untested' (or "
        "'proven' once a round-trip has been observed)"
    )


@pytest.mark.parametrize("spec", HARNESS_SPECS, ids=lambda s: s.family)
def test_headless_argv_renders_one_prompt_argument(spec: HarnessSpec) -> None:
    if not spec.is_harness:
        pytest.skip(f"{spec.family} has no headless turn")
    assert spec.headless_argv.count(PROMPT_SLOT) == 1, "exactly one prompt slot"

    prompt = 'a "quoted" prompt\nwith $shell chars & a newline'
    argv = spec.render_argv(prompt)
    assert argv[0] == spec.binary
    # The prompt must survive as exactly one argv element: rendering into a shell
    # string is how a turn carrying quotes or `$(…)` becomes an injection.
    assert argv.count(prompt) == 1
    assert len(argv) == len(spec.headless_argv) + 1


def test_non_harness_refuses_to_render() -> None:
    """`pplx` is a Search API client. Asking it for a turn is a bug, not a fallback."""
    spec = get_spec("perplexity")
    assert spec.adapter_status == "unsupported"
    assert not spec.is_harness
    with pytest.raises(ValueError, match="not an agent harness"):
        spec.render_argv("anything")


@pytest.mark.parametrize("spec", HARNESS_SPECS, ids=lambda s: s.family)
def test_every_harness_states_how_it_authenticates(spec: HarnessSpec) -> None:
    """A harness with no auth story at all cannot be graded past ``binary``."""
    if not spec.is_harness:
        return
    auth = spec.auth
    assert auth.env_vars or auth.credential_paths, f"{spec.family} has no auth probe"
    if not auth.unattended:
        # No API-key env var means no scheduled run can authenticate it. That is a
        # real constraint on the family, so it has to be written down, not implied.
        assert auth.login_command, f"{spec.family} needs a login_command"
        assert spec.note, f"{spec.family} must explain why it cannot run unattended"


@pytest.mark.parametrize("spec", HARNESS_SPECS, ids=lambda s: s.family)
def test_context_files_are_relative_and_described(spec: HarnessSpec) -> None:
    """Context paths are joined onto a workspace or ``~``; an absolute one escapes."""
    for context in spec.context_files:
        assert not context.path.startswith(("/", "~")), context.path
    if spec.is_harness:
        assert spec.context_files, (
            f"{spec.family} has nowhere to read coordination instructions from; "
            "an adapter would have no surface to install into"
        )


def test_agents_md_is_the_shared_surface() -> None:
    """The finding that shapes the whole adapter design, asserted rather than argued.

    Every harness in the table reads ``AGENTS.md``, marker-merged. That is why the
    right shape is one AGENTS.md-based family parameterized per harness, not N
    hand-written integrations.
    """
    harnesses = [s for s in HARNESS_SPECS if s.is_harness]
    for spec in harnesses:
        agents_md = [c for c in spec.context_files if c.path == "AGENTS.md"]
        assert agents_md, f"{spec.family} does not read AGENTS.md — revisit the shared design"
        assert agents_md[0].merge == "section", "AGENTS.md belongs to the user; merge a section"


def test_get_spec_names_the_known_families() -> None:
    assert get_spec("codex").binary == "codex"
    with pytest.raises(KeyError, match="unknown harness family"):
        get_spec("not-a-harness")
    assert set(SPECS_BY_FAMILY) == {spec.family for spec in HARNESS_SPECS}
