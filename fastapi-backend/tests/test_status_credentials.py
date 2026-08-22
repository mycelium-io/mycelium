# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The producer of the credential mapping, and the two ways a provider misdeclares.

``StatusRuntime`` takes ``credentials: Mapping[str, str]``; until now nothing made
one. ``status.credentials`` does, resolving explicit-over-ambient (a namespaced
env override, then the store, then a bare env var), and it has one job the rest
of the seam depends on: keep *absent* distinguishable from *configured-empty*, so
the runtime's error can say which. The conformance tests cover the other half of
the handoff: a provider that forgets ``auth`` or declares it in the wrong shape
is refused at registration instead of sinking a sweep.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from app.services.status import credentials
from app.services.status.auth import Basic, Bearer
from app.services.status.runtime import ProviderConformanceError, StatusRuntime
from app.services.status.types import Liveness, Ok, Ref, StatusProvider

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

#: Every credential name any test here resolves. The suite clears these (bare
#: and namespaced) from the ambient environment so it is hermetic: a machine that
#: exports one of them for an unrelated reason (a GITHUB_TOKEN for the GitHub
#: proxy, say) must not decide whether these tests pass.
_NAMES = (
    "GITHUB_TOKEN",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "CONFIGURED_EMPTY",
    "NEVER_SET",
    "EMPTY_TOKEN",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every name under test, bare and namespaced, from the environment."""
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"{credentials.NAMESPACE_PREFIX}{name}", raising=False)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the resolver at a throwaway store file and return a writer for it."""
    path = tmp_path / "status-credentials.json"
    monkeypatch.setenv(credentials.STORE_ENV, str(path))

    def write(mapping: dict[str, str]) -> None:
        path.write_text(json.dumps({"credentials": mapping}), encoding="utf-8")

    return write


# ── the resolver: explicit-over-ambient precedence ────────────────────────────


def test_a_stored_value_resolves(store):
    store({"GITHUB_TOKEN": "ghp_x"})
    assert credentials.resolve(["GITHUB_TOKEN"]) == {"GITHUB_TOKEN": "ghp_x"}


def test_the_namespaced_env_override_wins_over_the_file(store, monkeypatch: pytest.MonkeyPatch):
    # The deliberate override: MYCELIUM_STATUS_<NAME> beats the store.
    store({"GITHUB_TOKEN": "from_file"})
    monkeypatch.setenv(f"{credentials.NAMESPACE_PREFIX}GITHUB_TOKEN", "from_env")
    assert credentials.resolve(["GITHUB_TOKEN"]) == {"GITHUB_TOKEN": "from_env"}


def test_the_store_beats_an_ambient_bare_env_var(store, monkeypatch: pytest.MonkeyPatch):
    # The regression this whole precedence change exists for: an unrelated
    # GITHUB_TOKEN in the environment must not silently override a credential the
    # operator explicitly stored. The store wins; only the namespaced form can't.
    store({"GITHUB_TOKEN": "explicitly_stored"})
    monkeypatch.setenv("GITHUB_TOKEN", "ambient_proxy_token")
    assert credentials.resolve(["GITHUB_TOKEN"]) == {"GITHUB_TOKEN": "explicitly_stored"}


def test_a_bare_env_var_resolves_when_the_store_has_no_such_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # The convenience the handoff asked for is still there: a container with a
    # lone GITHUB_TOKEN and no store file works. It is just the lowest tier.
    monkeypatch.setenv(credentials.STORE_ENV, str(tmp_path / "does-not-exist.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    assert credentials.resolve(["GITHUB_TOKEN"]) == {"GITHUB_TOKEN": "ghp_env"}


def test_an_unset_name_is_absent_from_the_mapping(store):
    store({"GITHUB_TOKEN": "ghp_x"})
    resolved = credentials.resolve(["GITHUB_TOKEN", "JIRA_TOKEN"])
    assert "JIRA_TOKEN" not in resolved


def test_absent_is_not_empty(store):
    # The distinction the whole module exists to preserve: a name stored as ""
    # is present with an empty value; a name never stored is absent entirely.
    store({"CONFIGURED_EMPTY": ""})
    resolved = credentials.resolve(["CONFIGURED_EMPTY", "NEVER_SET"])
    assert resolved == {"CONFIGURED_EMPTY": ""}
    assert "CONFIGURED_EMPTY" in resolved
    assert "NEVER_SET" not in resolved


def test_an_empty_env_var_is_configured_empty_not_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv(credentials.STORE_ENV, str(tmp_path / "none.json"))
    monkeypatch.setenv("EMPTY_TOKEN", "")
    resolved = credentials.resolve(["EMPTY_TOKEN"])
    assert resolved == {"EMPTY_TOKEN": ""}


def test_a_missing_store_file_is_an_empty_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv(credentials.STORE_ENV, str(tmp_path / "never-written.json"))
    assert credentials.resolve(["GITHUB_TOKEN"]) == {}


def test_a_damaged_store_raises_rather_than_reading_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Corrupt is not absent. Reading it as empty would make every provider report
    # "not configured" when the truth is "your store is damaged".
    path = tmp_path / "status-credentials.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv(credentials.STORE_ENV, str(path))
    with pytest.raises(credentials.CredentialStoreError, match="not valid JSON"):
        credentials.resolve(["GITHUB_TOKEN"])


def test_a_non_string_stored_value_is_dropped_not_coerced(store):
    # A malformed entry must never render as a header, so it is not a credential.
    store({"GITHUB_TOKEN": "ghp_x", "BAD": cast("str", 12345)})
    assert credentials.resolve(["GITHUB_TOKEN", "BAD"]) == {"GITHUB_TOKEN": "ghp_x"}


def test_for_providers_resolves_each_schemes_declared_names(store):
    class Gh:
        auth = Bearer("GITHUB_TOKEN")

    class Jira:
        auth = Basic("JIRA_EMAIL", "JIRA_TOKEN")

    class NoAuth:
        auth = None

    store({"GITHUB_TOKEN": "ghp_x", "JIRA_EMAIL": "user@example.com", "JIRA_TOKEN": "tok"})
    providers = cast("list[StatusProvider]", [Gh(), Jira(), NoAuth()])
    resolved = credentials.for_providers(providers)
    assert resolved == {
        "GITHUB_TOKEN": "ghp_x",
        "JIRA_EMAIL": "user@example.com",
        "JIRA_TOKEN": "tok",
    }


# ── the runtime tells "not configured" from "set but empty" ───────────────────


class _Guarded:
    name = "guarded"
    base_url = "https://example.invalid"
    auth = Basic("JIRA_EMAIL", "JIRA_TOKEN")
    max_batch = 10
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def __init__(self) -> None:
        self.calls: list[list[Ref]] = []

    def claims(self, text: str) -> list[Ref]:
        return []

    async def fetch(self, refs, ctx):
        self.calls.append(list(refs))
        return [Ok(ref=r, liveness=Liveness(state="ok", label="ok")) for r in refs]


def _fake_factory(provider, auth):
    class _Ctx:
        http = None

        def log(self, message, **fields):
            return None

    return _Ctx()


@pytest.mark.asyncio
async def test_an_absent_credential_reads_as_not_configured():
    provider = _Guarded()
    rt = StatusRuntime(
        providers={provider.name: provider},
        context_factory=_fake_factory,
        credentials={"JIRA_EMAIL": "user@example.com"},
    )
    ref = Ref(provider="guarded", kind="x", id="1")
    answers = await rt.resolve([ref], NOW)
    assert provider.calls == []
    assert "JIRA_TOKEN not configured" in (answers[ref].error or "")


@pytest.mark.asyncio
async def test_a_configured_empty_credential_reads_as_set_but_empty():
    provider = _Guarded()
    rt = StatusRuntime(
        providers={provider.name: provider},
        context_factory=_fake_factory,
        # Present in the mapping, but empty: a different diagnosis from absent.
        credentials={"JIRA_EMAIL": "user@example.com", "JIRA_TOKEN": ""},
    )
    ref = Ref(provider="guarded", kind="x", id="1")
    answers = await rt.resolve([ref], NOW)
    assert provider.calls == []
    assert "JIRA_TOKEN set but empty" in (answers[ref].error or "")
    assert "not configured" not in (answers[ref].error or "")


# ── registration refuses a misdeclared provider ───────────────────────────────


class _ForgetsAuth:
    name = "forgetful"
    base_url = "https://example.invalid"
    max_batch = 10
    ttl = timedelta(minutes=1)
    swr = timedelta(minutes=30)

    def claims(self, text):
        return []

    async def fetch(self, refs, ctx):
        return []


class _WrongShapeAuth(_ForgetsAuth):
    name = "wrong-shape"
    auth = "GITHUB_TOKEN"  # the pre-scheme string form; not an AuthScheme


def test_a_provider_that_forgets_auth_is_refused_at_registration():
    # cast models the structural-Protocol gap the check exists to close: the type
    # checker is told to trust a provider that does not actually conform.
    provider = cast("StatusProvider", _ForgetsAuth())
    with pytest.raises(ProviderConformanceError, match="declares no 'auth'"):
        StatusRuntime(providers={"forgetful": provider})


def test_a_provider_with_the_wrong_auth_shape_is_refused_at_registration():
    # The exact reproduction from the handoff: auth = "GITHUB_TOKEN" would raise
    # AttributeError deep in the sweep and sink every provider. It is refused up
    # front instead, with a message naming the offender.
    provider = cast("StatusProvider", _WrongShapeAuth())
    with pytest.raises(ProviderConformanceError, match="wrong-shape"):
        StatusRuntime(providers={"wrong-shape": provider})


def test_a_valid_provider_passes_registration():
    provider = _Guarded()
    # No raise: a well-formed scheme (and None) is accepted.
    StatusRuntime(providers={provider.name: provider})
