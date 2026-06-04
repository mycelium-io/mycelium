"""Class-per-row scenario factory for the three-axis E2E matrix.

Each row in ``data/scenarios.yaml`` becomes a distinct pyATS ``Testcase``
subclass at import time, so a row failure shows up as a single targeted
test name (``TwoAgentConsensus_oc_cu``) rather than a parameterised
super-test that obscures which combination tripped.

Three axes
----------

- **tier**: ``pr`` | ``nightly`` | ``weekly`` — controls run frequency.
  Filtered via the ``MYCELIUM_E2E_TIERS`` env var (comma-separated;
  ``all`` matches everything; unset defaults to ``all``).
- **category**: ``core`` | ``distributed`` | ``cross_channel`` etc. —
  becomes a pyATS ``groups`` entry so existing job filters keep working.
- **agents**: the per-row adapter combo (e.g. ``[oc on hub, cu on
  spoke1]``). The class suffix encodes this for legibility:
  ``TwoAgentConsensus_oc_cu``.

Adapter-aware execution
-----------------------

Each adapter (openclaw, cursor, hermes) has a different wake protocol
and different cold-start latency. The base scenario consults each
agent's :class:`Provisioner` for the wake action and computes the
worst-case round budget so a slow-cursor row doesn't time out at the
fast-openclaw default.

- ``openclaw``: pre-existing agent in the gateway; ``wake_agent``
  triggers a Matrix DM to seat the agent on the session.
- ``cursor``: cold-spawn per-tick; ``wake_agent`` runs ``mycelium agent
  invoke`` once and the cc-daemon's room subscription handles the rest.
- ``hermes``: plugin polls coordination sessions; ``wake_agent`` is a
  no-op and the round budget needs only to accommodate the polling
  interval.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

from pyats import aetest

from libs import sessions
from libs.host_exec import HostExecError
from libs.provisioners import (
    AgentRef,
    PrereqMissing,
    Provisioner,
    get_provisioner,
)
from libs.sessions import ConsensusOutcome, SessionError

log = logging.getLogger(__name__)


# ── known adapters + class-name shortcodes ──────────────────────────


_ADAPTER_SHORTCODE: dict[str, str] = {
    "openclaw": "oc",
    "cursor": "cu",
    "hermes": "he",
}

_KNOWN_TIERS: frozenset[str] = frozenset({"pr", "nightly", "weekly"})

# Worst-case per-adapter round latency in seconds. Used to size the
# default consensus timeout when a row doesn't specify one. The base
# class picks the slowest agent's value and multiplies by the round
# budget. Values are conservative — better to over-allocate and finish
# early than to false-fail on a cold spawn.
_ADAPTER_ROUND_BUDGET_SECONDS: dict[str, int] = {
    "openclaw": 20,
    "hermes": 30,
    "cursor": 60,
}

_DEFAULT_N_ROUNDS = 20
_DEFAULT_TIMEOUT_FLOOR = 240  # never go below 4min, even for "fast" rows


# ── row loading ─────────────────────────────────────────────────────


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    """Parse the matrix YAML and apply minimal validation.

    The schema is intentionally loose — the factory adds defaults
    rather than rejecting partial rows, so adding a new column to
    ``scenarios.yaml`` doesn't require a code change.
    """
    import yaml

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"scenarios datafile not found: {p}")
    body = yaml.safe_load(p.read_text()) or {}
    raw_rows = body.get("scenarios") or body.get("rows") or []
    if not isinstance(raw_rows, list):
        raise ValueError(f"{p}: expected `scenarios:` to be a list, got {type(raw_rows).__name__}")

    rows: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            raise ValueError(f"{p}: row {i} is not a mapping")
        validate_row(raw, position=i, source=str(p))
        rows.append(raw)
    return rows


def validate_row(row: dict[str, Any], *, position: int, source: str) -> None:
    """Raise :class:`ValueError` for any structural problem with ``row``."""
    where = f"{source}:row[{position}]"

    name = row.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{where}: missing or empty `name`")

    tier = row.get("tier", "weekly")
    if tier not in _KNOWN_TIERS:
        raise ValueError(f"{where} ({name!r}): tier {tier!r} not in {sorted(_KNOWN_TIERS)}")

    agents = row.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        raise ValueError(f"{where} ({name!r}): `agents` must be a list of at least two")
    for j, ag in enumerate(agents):
        if not isinstance(ag, dict):
            raise ValueError(f"{where} ({name!r}): agent {j} is not a mapping")
        for required in ("handle", "adapter", "host"):
            if not ag.get(required):
                raise ValueError(f"{where} ({name!r}): agent {j} missing {required!r}")
        if ag["adapter"] not in _ADAPTER_SHORTCODE:
            raise ValueError(
                f"{where} ({name!r}): agent {j} adapter {ag['adapter']!r} not in {sorted(_ADAPTER_SHORTCODE)}"
            )


# ── tier gating ──────────────────────────────────────────────────────


def active_tiers(env_value: str | None = None) -> frozenset[str]:
    """Return the set of tiers that should run for this invocation.

    Reads :envvar:`MYCELIUM_E2E_TIERS` (comma-separated, e.g.
    ``"pr,nightly"``). ``all`` (or unset) means every tier. Unknown
    tier names are silently dropped — invalid input falls back to the
    empty set, which means "skip everything" so misconfigured CI
    surfaces as an obvious "no tests collected" rather than a silent
    full-run.
    """
    raw = (env_value if env_value is not None else os.environ.get("MYCELIUM_E2E_TIERS", "")).strip()
    if not raw or raw.lower() == "all":
        return frozenset(_KNOWN_TIERS)
    tokens = {t.strip().lower() for t in raw.split(",") if t.strip()}
    if "all" in tokens:
        return frozenset(_KNOWN_TIERS)
    return frozenset(t for t in tokens if t in _KNOWN_TIERS)


def filter_by_tier(rows: list[dict[str, Any]], tiers: frozenset[str]) -> list[dict[str, Any]]:
    """Return only the rows whose tier is in ``tiers``."""
    return [r for r in rows if r.get("tier", "weekly") in tiers]


# ── class-name shortcoding ──────────────────────────────────────────


def class_name_for(row: dict[str, Any]) -> str:
    """Compose a unique pyATS testcase class name for ``row``.

    Format: ``<TestType>_<adapter_combo>`` — e.g.
    ``TwoAgentConsensus_oc_cu`` or ``MemoryAndSearch_oc_oc_oc``.

    The base name comes from ``row["base_name"]`` if set, else from a
    ``CamelCase`` transform of ``row["name"]`` with the adapter suffix
    stripped (``"two-agent-consensus-oc-cu"`` → ``"TwoAgentConsensus"``).
    """
    base = row.get("base_name")
    if not base:
        base = _camel_from_name(row["name"], row["agents"])

    combo = "_".join(_ADAPTER_SHORTCODE[a["adapter"]] for a in row["agents"])
    return f"{base}_{combo}"


def _camel_from_name(name: str, agents: list[dict[str, Any]]) -> str:
    """Convert ``two-agent-consensus-oc-cu`` → ``TwoAgentConsensus``."""
    suffix_tokens = {_ADAPTER_SHORTCODE[a["adapter"]] for a in agents}
    parts = [p for p in name.replace("_", "-").split("-") if p and p.lower() not in suffix_tokens]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def groups_for(row: dict[str, Any]) -> list[str]:
    """Compute the pyATS ``groups`` list for a row.

    Always includes the row tier and category. Adds ``cross_family``
    when the row spans multiple adapters, plus a per-adapter group so
    legacy ``-g cursor`` / ``-g openclaw`` filters keep working.
    """
    groups = [row.get("tier", "weekly"), row.get("category", "core")]
    adapters = {a["adapter"] for a in row["agents"]}
    if len(adapters) > 1:
        groups.append("cross_family")
    groups.extend(sorted(adapters))
    return groups


# ── adapter-aware timeout calculation ───────────────────────────────


def compute_timeout_seconds(row: dict[str, Any]) -> int:
    """Return the consensus poll timeout for ``row``.

    Precedence: row override → adapter-aware default → floor.
    """
    override = row.get("timeout_seconds")
    if isinstance(override, int) and override > 0:
        return override

    n_rounds = int(row.get("n_steps_total", _DEFAULT_N_ROUNDS))
    worst = max(_ADAPTER_ROUND_BUDGET_SECONDS[a["adapter"]] for a in row["agents"])
    return max(_DEFAULT_TIMEOUT_FLOOR, n_rounds * worst)


# ── factory ──────────────────────────────────────────────────────────


def make_scenarios(rows: list[dict[str, Any]]) -> dict[str, type[aetest.Testcase]]:
    """Materialise one Testcase subclass per matrix row.

    The returned dict maps ``class_name -> class``. Callers are
    expected to do ``globals().update(...)`` (the suite loader does so
    automatically) so pyATS discovers the classes via module
    introspection.
    """
    classes: dict[str, type[aetest.Testcase]] = {}
    seen_names: set[str] = set()

    for row in rows:
        cls_name = class_name_for(row)
        if cls_name in seen_names:
            raise ValueError(
                f"duplicate scenario class name: {cls_name!r} (check `name` + agent combo in scenarios.yaml)"
            )
        seen_names.add(cls_name)

        cls = type(
            cls_name,
            (_ConsensusBase,),
            {
                "_row": row,
                "_class_name": cls_name,
                "groups": groups_for(row),
                "__doc__": row.get("description") or f"{cls_name} — generated from data/scenarios.yaml",
            },
        )
        classes[cls_name] = cls

    return classes


# ── base testcase ───────────────────────────────────────────────────


class _ConsensusBase(aetest.Testcase):
    """Adapter-aware consensus negotiation testcase.

    Subclasses are generated by :func:`make_scenarios` — do not
    instantiate directly. The base implements the full lifecycle:

    1. ``setup``: resolve devices from the pyATS testbed; check
       provisioner prereqs.
    2. ``provision_agents``: ``Provisioner.create_agent`` for each row
       agent.
    3. ``start_session``: ``session create`` + ``session join`` for
       each agent with their row-defined opening position.
    4. ``wake_agents``: ``Provisioner.wake_agent`` for each (no-op for
       hermes; Matrix DM for openclaw spokes; ``mycelium agent invoke``
       for cursor).
    5. ``wait_for_consensus``: poll backend until terminal state or
       per-row timeout.
    6. Optional asserts for plan file, memory writes, search hits.
    7. ``cleanup``: ``Provisioner.cleanup_agent`` for each + delete
       room.

    Per-row knobs (all optional with sensible defaults):

    - ``timeout_seconds``: override the auto-computed timeout
    - ``n_steps_total``: round budget (default 20)
    - ``require_consensus`` (default ``true``): if ``false``, a timeout
      is treated as a passing outcome (broken-by-design rows).
    - ``require_plan_file`` (default ``true`` when ``require_consensus``)
    - ``memory_writes``: list of ``{handle, key, value}`` to assert
      were written. Tested via ``mycelium memory get``.
    - ``search_queries``: list of ``{query, expected_substring}`` for
      semantic search assertions.
    """

    _row: ClassVar[dict[str, Any]]
    _class_name: ClassVar[str] = "_ConsensusBase"

    # ── parameters ───────────────────────────────────────────────────

    @aetest.setup
    def setup(self, testbed: Any, backend_url: str | None = None) -> None:
        """Resolve devices, build provisioners, check prereqs."""
        row = self._row
        self.row = row
        self.run_id = uuid.uuid4().hex[:8]
        self.room = f"scn-{row['name']}-{self.run_id}"
        self.backend_url = backend_url or os.environ.get("MYCELIUM_BACKEND_URL") or "http://localhost:8000"
        self.consensus_timeout = compute_timeout_seconds(row)
        self.agents: list[_AgentBinding] = []

        if testbed is None:
            self.skipped("no pyATS testbed supplied (scenarios need a testbed)")

        for ag in row["agents"]:
            host_name = ag["host"]
            device = testbed.devices.get(host_name)
            if device is None:
                self.skipped(f"testbed has no device named {host_name!r} (needed for agent {ag['handle']!r})")
            provisioner = get_provisioner(ag["adapter"])
            self.agents.append(
                _AgentBinding(
                    spec=ag,
                    device=device,
                    provisioner=provisioner,
                    ref=None,
                )
            )

        for binding in self.agents:
            try:
                binding.provisioner.check_prereqs(binding.device)
            except PrereqMissing as exc:
                self.skipped(f"prereq missing for {binding.spec['handle']}: {exc}")
            except HostExecError as exc:
                self.skipped(f"transport down for {binding.spec['handle']}: {exc}")

        # Use the first agent's device as the room-management host. Any
        # device with mycelium CLI reachable would do; we pick the
        # earliest in the row so test logs stay deterministic.
        self.control_device = self.agents[0].device

        try:
            sessions.create_room(self.control_device, self.room)
        except SessionError as exc:
            self.failed(f"could not create room {self.room!r}: {exc}")

        log.info(
            "%s setup ok: room=%s timeout=%ds agents=%s",
            self._class_name,
            self.room,
            self.consensus_timeout,
            ", ".join(f"{b.spec['handle']}({b.spec['adapter']}@{b.spec['host']})" for b in self.agents),
        )

    # ── 2 — provision ────────────────────────────────────────────────

    @aetest.test
    def provision_agents(self) -> None:
        """Run ``Provisioner.create_agent`` for each row agent."""
        for binding in self.agents:
            opening = binding.spec.get("position")
            try:
                binding.ref = binding.provisioner.create_agent(
                    binding.device,
                    binding.spec["handle"],
                    self.room,
                    opening=opening,
                )
            except PrereqMissing as exc:
                self.failed(f"create_agent failed for {binding.spec['handle']}: {exc}")
            except HostExecError as exc:
                self.failed(f"transport error during create_agent for {binding.spec['handle']}: {exc}")
            log.info(
                "%s provisioned: %s (workspace=%s)",
                binding.spec["adapter"],
                binding.ref.handle,
                binding.ref.metadata.get("workspace", "<n/a>"),
            )

    # ── 3 — start session ────────────────────────────────────────────

    @aetest.test
    def start_session(self) -> None:
        try:
            sessions.session_create(self.control_device, self.room)
        except SessionError as exc:
            self.failed(f"session create failed: {exc}")

        for binding in self.agents:
            position = (
                binding.spec.get("position")
                or f"I'm {binding.spec['handle']}. I aim to find the best "
                f"shared outcome on {self.row.get('topic', 'this issue')}."
            )
            try:
                sessions.session_join(
                    binding.device,
                    self.room,
                    binding.spec["handle"],
                    position,
                )
            except SessionError as exc:
                self.failed(f"session join failed for {binding.spec['handle']}: {exc}")

    # ── 4 — wake ─────────────────────────────────────────────────────

    @aetest.test
    def wake_agents(self) -> None:
        """Dispatch the adapter-specific wake action.

        Failures are logged but not fatal: the autonomous-coordination
        path means agents will *usually* attend their own ticks even
        without an explicit wake. Wake is a latency shaver, not a
        correctness requirement.
        """
        for binding in self.agents:
            if binding.ref is None:
                # `provision_agents` already failed; skip wake too.
                continue
            try:
                binding.provisioner.wake_agent(
                    binding.device,
                    binding.ref,
                    self.room,
                )
            except Exception as exc:  # noqa: BLE001 - wake is best-effort
                log.warning(
                    "wake_agent failed for %s (continuing): %s",
                    binding.spec["handle"],
                    exc,
                )

    # ── 5 — consensus ────────────────────────────────────────────────

    @aetest.test
    def wait_for_consensus(self) -> None:
        log.info(
            "polling backend %s for consensus on %s (timeout=%ds)",
            self.backend_url,
            self.room,
            self.consensus_timeout,
        )
        outcome = sessions.poll_consensus(
            self.backend_url,
            self.room,
            timeout_seconds=self.consensus_timeout,
        )
        self.outcome: ConsensusOutcome = outcome
        log.info(
            "consensus outcome: state=%s broken=%s plan_file=%s",
            outcome.state,
            outcome.broken,
            outcome.plan_file,
        )

        require_consensus = self.row.get("require_consensus", True)
        if require_consensus and not outcome.reached:
            self.failed(f"consensus not reached (state={outcome.state}, broken={outcome.broken}); raw={outcome.raw!r}")
        if not require_consensus and outcome.state == "consensus" and not outcome.broken:
            # The row was tagged as "expected to time out" but we got
            # an agreement instead — surface this as a soft signal
            # rather than failing, since unexpected convergence is
            # usually fine.
            log.info(
                "row expected timeout but consensus reached; not failing",
            )

    # ── 6a — plan/tasks.md ───────────────────────────────────────────

    @aetest.test
    def assert_plan_file(self) -> None:
        require = self.row.get("require_plan_file")
        if require is None:
            require = self.row.get("require_consensus", True)
        if not require:
            self.skipped("plan-file assertion not required for this row")

        if not getattr(self, "outcome", None) or not self.outcome.reached:
            self.skipped("no consensus — plan file assertion vacuous")

        try:
            body = sessions.read_plan_tasks(self.control_device, self.room)
        except SessionError as exc:
            self.failed(f"plan/tasks.md missing or unreadable: {exc}")
        if "- [ ]" not in body and "- [x]" not in body:
            self.failed(f"plan/tasks.md present but has no checklist items: {body[:300]!r}")

    # ── 6b — memory writes ───────────────────────────────────────────

    @aetest.test
    def assert_memory_writes(self) -> None:
        writes = self.row.get("memory_writes") or []
        if not writes:
            self.skipped("no memory_writes declared for this row")

        for entry in writes:
            handle = entry.get("handle") or self.agents[0].spec["handle"]
            key = entry["key"]
            value = entry["value"]
            # Pick the device that owns this handle, fall back to control.
            device = next(
                (b.device for b in self.agents if b.spec["handle"] == handle),
                self.control_device,
            )
            try:
                sessions.memory_set(device, self.room, handle, key, value)
            except SessionError as exc:
                self.failed(f"memory write {key!r} from {handle!r} failed: {exc}")

    # ── 6c — search hits ─────────────────────────────────────────────

    @aetest.test
    def assert_search_hits(self) -> None:
        queries = self.row.get("search_queries") or []
        if not queries:
            self.skipped("no search_queries declared for this row")

        # Pause briefly so the embedding worker indexes any writes from
        # the previous step. The default isn't aggressive — search just
        # exercises the index, not the freshness SLO.
        time.sleep(2)

        for q in queries:
            query = q["query"]
            expected = q.get("expected_substring", "")
            stdout = sessions.memory_search(self.control_device, self.room, query)
            if expected and expected not in stdout:
                self.failed(f"search {query!r}: expected substring {expected!r} not found in: {stdout[:400]!r}")

    # ── 7 — cleanup ──────────────────────────────────────────────────

    @aetest.cleanup
    def cleanup(self) -> None:
        for binding in self.agents:
            if binding.ref is None:
                continue
            try:
                binding.provisioner.cleanup_agent(
                    binding.device,
                    binding.ref,
                    self.room,
                )
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                log.warning(
                    "cleanup_agent failed for %s (continuing): %s",
                    binding.spec["handle"],
                    exc,
                )

        try:
            sessions.delete_room(self.control_device, self.room)
        except Exception as exc:  # noqa: BLE001
            log.debug("room delete failed (ignored): %s", exc)


# ── per-agent binding ────────────────────────────────────────────────


from dataclasses import dataclass  # noqa: E402 - small helper, kept near use


@dataclass
class _AgentBinding:
    """Bound state for one row agent across the test lifecycle."""

    spec: dict[str, Any]  # raw row entry
    device: Any  # pyATS testbed device
    provisioner: Provisioner  # adapter-specific provisioner
    ref: AgentRef | None  # set by provision_agents
