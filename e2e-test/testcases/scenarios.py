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
- **category**: ``core`` | ``distributed`` | ``cross_adapter`` etc. —
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

Testcase profiles (see ``profile`` in ``data/scenarios.yaml``) select
which pyATS sections exist on each generated class — ``consensus``
(negotiate + plan), ``full`` (+ memory + search), or ``shakedown``
(session terminal state only). Tier (``pr`` / ``nightly`` / ``weekly``)
filters which rows run; profile filters what each row tests.
"""

from __future__ import annotations

import hashlib
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

# Testcase shape — chosen at class materialisation time, not via skipping
# subtests.  ``consensus`` = negotiate + plan; ``full`` adds memory +
# search; ``shakedown`` = session terminal state only (timeouts OK).
_KNOWN_PROFILES: frozenset[str] = frozenset({"consensus", "full", "shakedown"})

# Worst-case per-adapter round latency in seconds. Used to size the
# default consensus timeout when a row doesn't specify one. The base
# class picks the slowest agent's value and multiplies by the round
# budget. Values are conservative — better to over-allocate and finish
# early than to false-fail on a cold spawn.
_ADAPTER_ROUND_BUDGET_SECONDS: dict[str, int] = {
    "openclaw": 25,
    "hermes": 30,
    "cursor": 60,
}

_DEFAULT_N_ROUNDS = 20
# Floor must outlast the BACKEND's CFN session budget (300s
# negotiation_time_seconds default) plus the abort/plan-compiler tail
# (~30s) plus the per-test join window (~30s). The 240s floor we used
# to ship would silently false-fail any 3+ agent test where the LLMs
# bickered through their full n_steps_total — see ThreeAgentReturnTrip
# failure in the 2026-06-07 lab run.
_DEFAULT_TIMEOUT_FLOOR = 360

# Multi-agent synchronization tax. Each agent past 2 adds non-trivial
# overhead: round trips wait on the *slowest* reply, the proposer
# rotation logic enforces strict turn order, and the CFN
# decide-negotiation call grows with the message history. A flat 15%
# bump per extra agent matches what we saw in lab traces (3 OC agents
# ran ~14s/round versus the 2-agent ~10s baseline).
_PER_AGENT_ROUND_OVERHEAD = 0.15


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
        # Normalise profile early so load_rows catches misconfigurations.
        raw["profile"] = profile_for_row(raw)
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

    profile = row.get("profile")
    if profile is not None and profile not in _KNOWN_PROFILES:
        raise ValueError(f"{where} ({name!r}): profile {profile!r} not in {sorted(_KNOWN_PROFILES)}")


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


def profile_for_row(row: dict[str, Any]) -> str:
    """Return the testcase profile for ``row``.

    Profiles control which pyATS sections exist on the generated class
    (not which sections skip at runtime):

    - ``consensus`` — setup → wake → poll → plan file → cleanup
    - ``full`` — consensus path + memory writes + search hits
    - ``shakedown`` — setup → wake → poll → cleanup (no plan/memory/search)

    An explicit ``profile`` key wins. Otherwise: rows with both
    ``memory_writes`` and ``search_queries`` become ``full``; rows with
    ``require_consensus: false`` become ``shakedown``; everything else
    is ``consensus``.
    """
    explicit = row.get("profile")
    if explicit is not None:
        if explicit not in _KNOWN_PROFILES:
            raise ValueError(
                f"row {row.get('name')!r}: profile {explicit!r} not in {sorted(_KNOWN_PROFILES)}"
            )
        return explicit

    has_memory = bool(row.get("memory_writes"))
    has_search = bool(row.get("search_queries"))
    if has_memory or has_search:
        if not (has_memory and has_search):
            raise ValueError(
                f"row {row.get('name')!r}: memory_writes and search_queries must both be "
                "set for a full-profile row (or set profile explicitly)"
            )
        return "full"

    if row.get("require_consensus") is False:
        return "shakedown"

    return "consensus"


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


def room_name_for_row(row: dict[str, Any], run_id: str) -> str:
    """Deterministic parent-room name for a matrix row.

    Postgres LISTEN/NOTIFY channel names cap at 63 bytes; the backend
    uses ``room:<room>:session:<8char>`` (22 fixed bytes) for session
    channels, leaving 41 bytes for the parent room name. ``scn-`` +
    ``-<run_id>`` eats 13, so the row slug must stay ≤ 28 bytes.
    """
    slug = row["name"]
    if len(slug) > 28:
        slug = f"{slug[:18]}-{hashlib.sha1(slug.encode()).hexdigest()[:6]}"
    return f"scn-{slug}-{run_id}"


def compute_timeout_seconds(row: dict[str, Any]) -> int:
    """Return the consensus poll timeout for ``row``.

    Precedence: row override → adapter-aware default → floor.

    The adapter-aware default is ``n_rounds * worst_adapter_round_budget
    * (1 + 0.15 * (n_agents - 2))`` for ``n_agents > 2``, then clamped
    to ``_DEFAULT_TIMEOUT_FLOOR``. The multi-agent tax models the
    observed lab behavior that 3-agent OC rounds run ~40% slower than
    2-agent rounds (round trip blocks on the slowest reply + proposer
    rotation lengthens the wait queue).
    """
    override = row.get("timeout_seconds")
    if isinstance(override, int) and override > 0:
        return override

    n_rounds = int(row.get("n_steps_total", _DEFAULT_N_ROUNDS))
    worst = max(_ADAPTER_ROUND_BUDGET_SECONDS[a["adapter"]] for a in row["agents"])
    n_agents = len(row["agents"])
    multi_agent_tax = 1.0 + _PER_AGENT_ROUND_OVERHEAD * max(0, n_agents - 2)
    return max(_DEFAULT_TIMEOUT_FLOOR, int(n_rounds * worst * multi_agent_tax))


# ── factory ──────────────────────────────────────────────────────────


_PROFILE_BASE: dict[str, type] = {}  # filled after base classes are defined


def make_scenarios(rows: list[dict[str, Any]]) -> dict[str, type[aetest.Testcase]]:
    """Materialise one Testcase subclass per matrix row.

    The returned dict maps ``class_name -> class``. Callers are
    expected to do ``globals().update(...)`` (the suite loader does so
    automatically) so pyATS discovers the classes via module
    introspection.

    Each row's ``profile`` (see :func:`profile_for_row`) selects the
    base class — optional assertions are omitted entirely rather than
    registered as skipping subtests.
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

        profile = row.get("profile") or profile_for_row(row)
        base = _PROFILE_BASE.get(profile)
        if base is None:
            raise ValueError(f"row {row.get('name')!r}: unknown profile {profile!r}")

        cls = type(
            cls_name,
            (base,),
            {
                "_row": row,
                "_class_name": cls_name,
                "_profile": profile,
                "groups": groups_for(row),
                "__doc__": row.get("description") or f"{cls_name} — generated from data/scenarios.yaml",
            },
        )
        classes[cls_name] = cls

    return classes


# ── base testcase ───────────────────────────────────────────────────


class _ScenarioCore(aetest.Testcase):
    """Shared negotiation lifecycle: setup → wake → poll → cleanup.

    Subclasses are generated by :func:`make_scenarios` — do not
    instantiate directly. Profile-specific classes add plan / memory /
    search sections; this core never registers optional subtests that
    skip at runtime.
    """

    _row: ClassVar[dict[str, Any]]
    _class_name: ClassVar[str] = "_ScenarioCore"
    _profile: ClassVar[str] = "consensus"

    # ── parameters ───────────────────────────────────────────────────

    @aetest.setup
    def setup(
        self,
        testbed: Any,
        backend_url: str | None = None,
        testscript: Any = None,
    ) -> None:
        """Build bindings, create per-scenario room + session.

        The heavy work (provisioning OpenClaw agents at the gateway)
        ran in ``LabRedeployCommonSetup.provision_matrix_agents`` so
        this method only does the lightweight per-scenario plumbing:
        room create → register each agent in the room → session
        create → session join. Everything is captured in
        ``self.parameters`` so :meth:`cleanup` can tear it down even
        if one of the later test sections aborts.

        Falls back to the legacy one-shot path (ensure_runtime +
        register_in_room) for adapters/agents that common_setup did
        NOT pre-provision — useful when running scenarios outside
        the suite (e.g. ``pyats run testcases/scenarios.py``).
        """
        row = self._row
        self.row = row
        suite_room: str | None = None
        if testscript is not None:
            suite_room = testscript.parameters.get("suite_shared_room")
        self._suite_shared_room = bool(suite_room)
        if suite_room:
            self.room = suite_room
            self.run_id = testscript.parameters.get("suite_run_id") or "suite"
        else:
            self.run_id = uuid.uuid4().hex[:8]
            self.room = room_name_for_row(row, self.run_id)
        self.backend_url = backend_url or os.environ.get("MYCELIUM_BACKEND_URL") or "http://localhost:8000"
        self.consensus_timeout = compute_timeout_seconds(row)
        self.agents: list[_AgentBinding] = []

        # Pull the matrix-wide agent registry that
        # ``provision_matrix_agents`` deposited. Keys are tuples of
        # ``(adapter, handle, host)`` so we can find the AgentRef that
        # matches our row's spec exactly.
        provisioned: dict[tuple[str, str, str], AgentRef] = {}
        if testscript is not None:
            provisioned = testscript.parameters.get("provisioned_agents", {}) or {}

        if testbed is None:
            self.skipped("no pyATS testbed supplied (scenarios need a testbed)")

        # ── resolve devices + provisioners ────────────────────────
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

        # ── prereq check ───────────────────────────────────────────
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

        if not self._suite_shared_room:
            # ── create per-scenario room ──────────────────────────
            try:
                sessions.create_room(self.control_device, self.room)
            except SessionError as exc:
                self.failed(f"could not create room {self.room!r}: {exc}")

            # The backend (Docker, runs as root) creates the room dir
            # via a volume mount, so without reclaiming ownership the
            # CLI's per-agent ``mycelium agent add`` call fails to
            # write the manifest.
            self._chown_mycelium_on_agent_hosts()

            # ── register each agent in this room ──────────────────
            for binding in self.agents:
                key = (binding.spec["adapter"], binding.spec["handle"], binding.spec["host"])
                opening = binding.spec.get("position")

                if key in provisioned:
                    # Suite common_setup already ran ensure_runtime (or
                    # discovery allocated an existing agent). Use the actual
                    # handle from the provisioned ref — it may differ from
                    # the spec handle when an existing agent was reused.
                    actual_handle = provisioned[key].handle
                else:
                    # No suite common_setup (running standalone). Fall back
                    # to the spec handle for a fresh ensure_runtime.
                    try:
                        binding.provisioner.ensure_runtime(binding.device, binding.spec["handle"])
                    except PrereqMissing as exc:
                        self.failed(
                            f"ensure_runtime failed for {binding.spec['handle']} (no common_setup ran): {exc}"
                        )
                    actual_handle = binding.spec["handle"]

                try:
                    binding.ref = binding.provisioner.register_in_room(
                        binding.device,
                        actual_handle,
                        self.room,
                        opening=opening,
                    )
                except PrereqMissing as exc:
                    self.failed(f"register_in_room failed for {binding.actual_handle}: {exc}")
                except HostExecError as exc:
                    self.failed(f"transport error during register_in_room for {binding.actual_handle}: {exc}")
        else:
            # Suite mode: agents were registered to the shared room in
            # CommonSetup. Reuse the ensure_runtime refs — no gateway
            # restart here.
            for binding in self.agents:
                key = (binding.spec["adapter"], binding.spec["handle"], binding.spec["host"])
                binding.ref = provisioned.get(key)
                if binding.ref is None:
                    self.failed(
                        f"no provisioned ref for {binding.spec['handle']} "
                        f"(suite_shared_room={self.room!r})"
                    )

            try:
                sessions.wait_for_no_active_sessions(self.backend_url, self.room)
            except SessionError as exc:
                self.failed(f"stale coordination session on {self.room!r}: {exc}")

        # ── create session + per-agent joins ──────────────────────
        try:
            self.session_room = sessions.session_create(
                self.control_device,
                self.room,
                backend_url=self.backend_url,
            )
        except SessionError as exc:
            self.failed(f"session create failed: {exc}")

        log.info(
            "%s session created: %s",
            self._class_name,
            self.session_room,
        )

        for binding in self.agents:
            position = (
                binding.spec.get("position")
                or f"I'm {binding.actual_handle}. I aim to find the best "
                f"shared outcome on {self.row.get('topic', 'this issue')}."
            )
            try:
                sessions.session_join(
                    binding.device,
                    self.room,
                    binding.actual_handle,
                    position,
                )
            except SessionError as exc:
                self.failed(f"session join failed for {binding.actual_handle}: {exc}")

        log.info(
            "%s setup ok: room=%s timeout=%ds agents=%s",
            self._class_name,
            self.room,
            self.consensus_timeout,
            ", ".join(
                f"{b.actual_handle}({b.spec['adapter']}@{b.spec['host']})"
                + (f"[spec={b.spec['handle']}]" if b.actual_handle != b.spec["handle"] else "")
                for b in self.agents
            ),
        )

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
                # Setup never produced a ref for this binding (a prior
                # ``self.failed(...)`` halted setup mid-loop). Skip
                # wake — the testcase will already be marked failed
                # by the time pyATS reaches this section.
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
    def poll_for_consensus(self) -> None:
        if not self.agents:
            self.failed("setup did not complete (no testbed or prereqs not met)")
        log.info(
            "polling backend %s for consensus on %s (timeout=%ds)",
            self.backend_url,
            getattr(self, "session_room", self.room),
            self.consensus_timeout,
        )
        outcome = sessions.poll_consensus(
            self.backend_url,
            self.room,
            session_room=getattr(self, "session_room", None),
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

    @aetest.cleanup
    def cleanup(self) -> None:
        """Unregister agents from this room and optionally delete the room.

        Agent unregistration always runs — it removes the room from each
        agent's adapter config (openclaw.json / hermes config) on the remote
        host, releasing the SSE LISTEN connection.  Room deletion is skipped
        when MYCELIUM_E2E_KEEP_ROOMS=1 so the room data survives for
        post-test inspection, but the SSE subscriptions are still torn down.
        """
        keep_rooms = os.environ.get("MYCELIUM_E2E_KEEP_ROOMS", "").lower() in {"1", "true", "yes"}

        # Suite-shared rooms: just drain the session, never delete the room.
        if getattr(self, "_suite_shared_room", False):
            session_room = getattr(self, "session_room", None)
            if session_room:
                try:
                    sessions.wait_for_session_terminal(
                        self.backend_url,
                        self.room,
                        session_room,
                        timeout_seconds=sessions._SUITE_SESSION_DRAIN_SECONDS,
                    )
                except SessionError as exc:
                    log.warning(
                        "cleanup: session %s not terminal on %s: %s",
                        session_room,
                        self.room,
                        exc,
                    )
            try:
                sessions.wait_for_no_active_sessions(
                    self.backend_url,
                    self.room,
                    timeout_seconds=sessions._SUITE_SESSION_DRAIN_SECONDS,
                )
            except SessionError as exc:
                log.warning("cleanup: session still active on %s: %s", self.room, exc)
            return

        # Always unregister agents — this removes the room from each agent's
        # adapter config on the remote host (openclaw.json, hermes config)
        # so stale SSE LISTEN connections are released even when keeping rooms.
        for binding in self.agents:
            if binding.ref is None:
                continue
            try:
                binding.provisioner.unregister_from_room(
                    binding.device,
                    binding.ref,
                    self.room,
                )
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                log.warning(
                    "unregister_from_room failed for %s (continuing): %s",
                    binding.spec["handle"],
                    exc,
                )

        if keep_rooms:
            log.info("cleanup: keeping room %s (MYCELIUM_E2E_KEEP_ROOMS)", self.room)
            return

        try:
            sessions.delete_room(self.control_device, self.room)
        except Exception as exc:  # noqa: BLE001
            log.debug("room delete failed (ignored): %s", exc)

    def _chown_mycelium_on_agent_hosts(self) -> None:
        """Reclaim user ownership of ``~/.mycelium`` on each agent host."""
        seen_ids: set[int] = set()
        targets: list[Any] = []
        for d in (self.control_device, *[b.device for b in self.agents]):
            if id(d) in seen_ids:
                continue
            seen_ids.add(id(d))
            targets.append(d)

        from libs import host_exec
        from libs.host_exec import HostExecError

        for device in targets:
            try:
                host_exec.execute(
                    device,
                    'if [ -d "$HOME/.mycelium" ]; then '
                    'sudo chown -R "$USER:$USER" "$HOME/.mycelium" '
                    "2>/dev/null || true; fi",
                    shell=True,
                    timeout=20.0,
                )
            except HostExecError as exc:
                log.debug(
                    "chown ~/.mycelium failed on %s (continuing): %s",
                    getattr(device, "name", device),
                    exc,
                )


class _ConsensusScenario(_ScenarioCore):
    """Negotiate to agreement and verify ``plan/tasks.md``."""

    _profile: ClassVar[str] = "consensus"

    @aetest.test
    def assert_plan_file(self) -> None:
        if not getattr(self, "outcome", None) or not self.outcome.reached:
            self.failed("consensus not reached — plan/tasks.md assertion requires agreement")

        try:
            body = sessions.read_plan_tasks(self.control_device, self.room)
        except SessionError as exc:
            self.failed(f"plan/tasks.md missing or unreadable: {exc}")
        if "- [ ]" not in body and "- [x]" not in body:
            self.failed(f"plan/tasks.md present but has no checklist items: {body[:300]!r}")


class _FullScenario(_ConsensusScenario):
    """Consensus + plan + memory persistence + semantic search."""

    _profile: ClassVar[str] = "full"

    @aetest.test
    def assert_memory_writes(self) -> None:
        writes = self.row.get("memory_writes") or []
        if not writes:
            self.failed("full-profile row missing memory_writes")

        self._chown_mycelium_on_agent_hosts()

        for entry in writes:
            spec_handle = entry.get("handle") or self.agents[0].spec["handle"]
            key = entry["key"]
            value = entry["value"]
            # Look up by spec handle (as declared in scenarios.yaml);
            # use the actual (possibly discovered) handle for the CLI call.
            binding = next(
                (b for b in self.agents if b.spec["handle"] == spec_handle),
                None,
            )
            device = binding.device if binding else self.control_device
            actual_handle = binding.actual_handle if binding else spec_handle
            try:
                sessions.memory_set(device, self.room, actual_handle, key, value)
            except SessionError as exc:
                self.failed(f"memory write {key!r} from {actual_handle!r} failed: {exc}")

    @aetest.test
    def assert_search_hits(self) -> None:
        queries = self.row.get("search_queries") or []
        if not queries:
            self.failed("full-profile row missing search_queries")

        time.sleep(2)

        for q in queries:
            query = q["query"]
            expected = q.get("expected_substring", "")
            stdout = sessions.memory_search(self.control_device, self.room, query)
            if expected and expected not in stdout:
                self.failed(f"search {query!r}: expected substring {expected!r} not found in: {stdout[:400]!r}")


class _ShakedownScenario(_ScenarioCore):
    """Session plumbing only — terminal state required, agreement optional."""

    _profile: ClassVar[str] = "shakedown"


_PROFILE_BASE.update(
    {
        "consensus": _ConsensusScenario,
        "full": _FullScenario,
        "shakedown": _ShakedownScenario,
    }
)

# Back-compat alias for suite loaders that reference the old name.
_ConsensusBase = _ConsensusScenario


# ── per-agent binding ────────────────────────────────────────────────


from dataclasses import dataclass  # noqa: E402 - small helper, kept near use


@dataclass
class _AgentBinding:
    """Bound state for one row agent across the test lifecycle."""

    spec: dict[str, Any]  # raw row entry
    device: Any  # pyATS testbed device
    provisioner: Provisioner  # adapter-specific provisioner
    ref: AgentRef | None  # set during setup's register_in_room loop

    @property
    def actual_handle(self) -> str:
        """Real agent handle — may differ from spec if a discovered agent was allocated.

        Use this (not ``spec["handle"]``) for all CLI operations after
        setup's register_in_room loop has run.  Before that point
        ``ref`` is None and this falls back to the spec handle.
        """
        return self.ref.handle if self.ref is not None else self.spec["handle"]
