"""Shared fixtures for the Mycelium end-to-end integration tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

# Repo root (parent of tests/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mycelium_e2e.bundle import (  # noqa: E402
    TestContext,
    cleanup,
    cleanup_distributed,
    cleanup_stale_sessions,
    detect_environment,
    print_results,
    wait_for_agents_idle,
)
from mycelium_e2e.config import BACKEND_URL, ROOM_PREFIX  # noqa: E402

# Retain context for the legacy-style summary printed after the session.
_ctx_holder: dict[str, Any] = {}
_ran_distributed: bool = False

# Coordination states that mean "the backend (or an agent) is still doing work
# on this session". If the test has already returned, anything in this set is
# a leak — most often because the test's per-phase timeout (e.g. 240s for
# `wait_for_mycelium_consensus`) was shorter than the actual time the agents
# took to converge, so pytest gave up while CFN/agents kept ticking. Empirical
# example from a 2026-04-20 run: test_41_distributed_three_agent declared
# "Coordination consensus reached: None" at 240s, but agents kept producing
# valid coordination_ticks for another 5 minutes against a session whose row
# was still `negotiating`. Those leaks burn CFN/LLM quota and can starve
# subsequent tests, which is why we reap them here per-test rather than
# only at session start (and again at session end via cleanup_stale_sessions).
_LEAKED_STATES = ("negotiating", "waiting", "synthesizing")


def _kill_stale_pytest_processes() -> None:
    """Kill any pre-existing pytest processes running the e2e suite.

    Concurrent runs share the same backend and their reapers delete each
    other's session rooms, causing spurious 404s mid-negotiation.
    """
    import subprocess

    my_pid = os.getpid()
    my_ppid = os.getppid()
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pytest.*test_mycelium_e2e"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            pid = int(line.strip())
            if pid in (my_pid, my_ppid):
                continue
            print(
                f"  [GUARD] killing stale pytest process {pid} "
                f"to prevent cross-run interference"
            )
            os.kill(pid, 9)
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass


def _presuite_sanity_checks() -> None:
    """Run before the test suite to ensure a clean environment.

    Addresses known failure modes:
      - Orphan session rooms left by previous crashed/timed-out runs
      - Agent session history bloat causing context overflow (#175 comment)
      - Runaway agent processes from leaked sessions
      - Stale mycelium_room messages that re-trigger agents
    """
    print("\n[SETUP] Running pre-suite sanity checks...")

    # 1. Kill stale pytest processes (already existed, moved here for clarity)
    _kill_stale_pytest_processes()

    # 2. Clean up ALL stale sessions (not just old ones — any failed/negotiating)
    for prefix in ("e2e-", "dist-e2e-", "mycelium_room:session:"):
        cleaned = cleanup_stale_sessions(prefix=prefix, max_age_minutes=0)
        if cleaned:
            print(f"  [SETUP] Cleaned {cleaned} stale '{prefix}*' session(s)")

    # 3. Trim agent session history to prevent context bloat.
    #    The gateway accumulates .jsonl files in ~/.openclaw/agents/<id>/sessions/
    #    which bloat agent context windows and cause narration instead of tool use.
    _trim_agent_sessions(max_files=5)

    # 4. Trim agent session history on remote hosts too
    _trim_remote_agent_sessions(max_files=5)

    # 5. Logical reset of each agent's negotiation-carrying sessions via gateway
    #    RPC. Trimming jsonl files (steps 3 & 4) caps disk usage but does NOT
    #    clear the live in-memory conversation context — the gateway keeps
    #    using whatever sessionId is current. Without this step, agents enter
    #    a fresh suite carrying the prior run's negotiation transcript, which
    #    can push a 3-agent negotiation past the model's context window
    #    (observed: agent-alpha at 148k/200k after one suite, causing test_31
    #    and test_41 to lose the 3rd agent to silent refusal/truncation), and
    #    can also leave stale "I already joined" history in matrix-channel
    #    sessions so that the LLM no-ops on the next negotiation trigger.
    _reset_agent_mycelium_sessions()

    # 6. Wait for any in-flight agent turns to finish
    counts = wait_for_agents_idle(timeout=15, poll_interval=2.0)
    busy = {h: c for h, c in counts.items() if c > 0}
    if busy:
        print(f"  [SETUP] Warning: agents still busy after 15s: {busy}")
    else:
        print("  [SETUP] All agents idle")

    print("[SETUP] Pre-suite checks complete\n")


def _trim_agent_sessions(max_files: int = 5) -> None:
    """Remove excess .jsonl session files for local agents.

    Keeps the most recent ``max_files`` per agent to preserve some context,
    but prevents the unbounded growth that causes context overflow.
    """
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.exists():
        return
    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.exists():
            continue
        jsonl_files = sorted(
            sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime
        )
        excess = len(jsonl_files) - max_files
        if excess > 0:
            for f in jsonl_files[:excess]:
                f.unlink(missing_ok=True)
            print(
                f"  [SETUP] Trimmed {excess} session file(s) for "
                f"{agent_dir.name} (kept {max_files})"
            )


def _trim_remote_agent_sessions(
    max_files: int = 5,
    hosts: list[str] | None = None,
    ssh_key: str = "~/.ssh/ioc.pem",
    user: str = "ubuntu",
) -> None:
    """Trim .jsonl session files on remote gateway hosts."""
    if hosts is None:
        hosts = [
            os.environ.get("OCLW3_IP", "10.0.50.171"),
            os.environ.get("OCLW5_IP", "10.0.50.142"),
        ]
    key_path = os.path.expanduser(ssh_key)
    if not os.path.exists(key_path):
        return
    for host in hosts:
        cmd = (
            f"for d in ~/.openclaw/agents/*/sessions; do "
            f"  [ -d \"$d\" ] || continue; "
            f"  count=$(ls -1 \"$d\"/*.jsonl 2>/dev/null | wc -l); "
            f"  if [ \"$count\" -gt {max_files} ]; then "
            f"    ls -1t \"$d\"/*.jsonl | tail -n +{max_files + 1} | xargs rm -f; "
            f'    echo "trimmed $d: $count -> {max_files}"; '
            f"  fi; "
            f"done"
        )
        try:
            result = subprocess.run(
                [
                    "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5", f"{user}@{host}", cmd,
                ],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                if line:
                    print(f"  [SETUP] {host}: {line}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass


# Agents per host. Mirrors mycelium_e2e.distributed_e2e.DISTRIBUTED_AGENTS but
# kept local to avoid coupling conftest to that module's heavier imports
# (distributed_e2e pulls in httpx, matrix client deps, etc.).
_AGENTS_BY_HOST: dict[str | None, tuple[str, ...]] = {
    None: ("agent-alpha", "agent-beta", "agent-gamma", "agent-delta"),  # local oclw4
    os.environ.get("OCLW3_IP", "10.0.50.171"): ("claire-agent",),
    os.environ.get("OCLW5_IP", "10.0.50.142"): ("oclw5-agent",),
}


def _run_openclaw(
    args: list[str],
    *,
    host: str | None = None,
    ssh_key: str = "~/.ssh/ioc.pem",
    user: str = "ubuntu",
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``openclaw <args>`` locally or via ssh; return CompletedProcess or
    None on connection failure / missing key. Never raises.

    On remote hosts ``openclaw`` is installed via nvm, which is not on the
    non-interactive PATH. We source nvm explicitly so the shim resolves
    without requiring user-level shell config tweaks.
    """
    if host is None:
        try:
            return subprocess.run(
                ["openclaw", *args],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None

    key_path = os.path.expanduser(ssh_key)
    if not os.path.exists(key_path):
        return None
    # Argument-array → single shell command for the remote bash. shlex.quote
    # each arg to keep the JSON / nested quoting in --params intact.
    import shlex
    remote_cmd = " ".join(shlex.quote(a) for a in ["openclaw", *args])
    full_remote = (
        '[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1; '
        + remote_cmd
    )
    cmd = [
        "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5", f"{user}@{host}", full_remote,
    ]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


_RESET_SESSION_TAGS: tuple[str, ...] = (
    # Direct mycelium-room channel that carries CognitiveEngine ticks/replies.
    "mycelium-room",
    # Matrix channel where negotiation triggers land for local agents. The
    # negotiation tests (e.g. ``test_31_local_three_agent_negotiation``) send
    # the trigger to a Matrix room; if the agent's matrix-channel session is
    # carrying stale "I already joined" history from earlier suite runs, the
    # LLM emits a no-op acknowledgement instead of calling ``mycelium session
    # join`` again, leaving the backend at ``n_agents: 1`` and the test failing
    # with "Only 1/3 agents responded". Resetting these clears that history.
    "matrix:channel:",
)


def _list_mycelium_sessions(
    agent_id: str, *, host: str | None = None,
) -> list[dict[str, Any]]:
    """List the agent's sessions that carry negotiation traffic.

    Includes both the direct ``mycelium-room`` channel (CognitiveEngine
    ticks/replies) and the ``matrix:channel:`` sessions where local agents
    receive negotiation triggers. Returns an empty list on any error; safe
    for best-effort use."""
    proc = _run_openclaw(
        ["sessions", "--agent", agent_id, "--json", "--limit", "100"],
        host=host,
        timeout=20.0,
    )
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    sessions = data if isinstance(data, list) else data.get("sessions", [])
    # Session keys observed:
    #   agent:agent-alpha:mycelium-room:group:mycelium_room
    #   agent:agent-gamma:matrix:channel:!xsqgkkmaxjhhtwqlte:local
    return [
        s for s in sessions
        if any(
            tag in (s.get("key") or s.get("sessionKey") or "")
            for tag in _RESET_SESSION_TAGS
        )
    ]


def _reset_session(key: str, *, host: str | None = None) -> bool:
    """Call gateway RPC ``sessions.reset`` for a single session key.
    Returns True on a 0 exit code, False otherwise. Best-effort, never raises."""
    proc = _run_openclaw(
        [
            "gateway", "call", "sessions.reset",
            "--params", json.dumps({"key": key}),
        ],
        host=host,
        timeout=15.0,
    )
    return proc is not None and proc.returncode == 0


def _reset_agent_mycelium_sessions(
    agents_by_host: dict[str | None, tuple[str, ...]] | None = None,
) -> None:
    """Logical reset of each agent's negotiation-carrying session(s) via gateway RPC.

    Covers both the direct ``mycelium-room`` channel (where CognitiveEngine
    ticks and replies flow) and the ``matrix:channel:`` sessions where local
    agents receive negotiation triggers — see ``_RESET_SESSION_TAGS``.

    Why this matters:
        Trimming .jsonl files (the older approach) caps disk usage but does
        not clear the live in-memory conversation context the gateway feeds
        to the LLM. Two distinct failure modes were observed without this:

        1. Context bloat on the ``mycelium-room`` channel: with the e2e suite
           running ~10 distributed negotiations per pass and each round
           writing both an `offer` and an `accept` into the session,
           accumulated input context grew to ~74% of the model context
           window — causing ``test_31``/``test_41`` to lose the 3rd agent to
           silent refusal or 3-token degenerate output.

        2. Stale "I already joined" history on the ``matrix:channel:``
           session: after a prior trigger in the same suite, the agent's
           transcript already contains its "Joined." reply. When the next
           trigger lands, the LLM emits a no-op acknowledgement instead of
           re-calling ``mycelium session join``, leaving the backend at
           ``n_agents: 1`` and the negotiation never reaching the 3rd agent.

        ``sessions.reset`` is the gateway-supported way to clear both without
        deleting on-disk transcripts (so forensics survives a reset) or
        restarting the gateway (which would also drop healthy sessions).

    Best-effort: skips hosts without ssh key, agents without sessions, and
    individual resets that fail. Suite continues regardless.
    """
    targets = agents_by_host or _AGENTS_BY_HOST
    total_reset = 0
    total_failed = 0

    for host, agent_ids in targets.items():
        label = host or "local"
        for agent_id in agent_ids:
            sessions = _list_mycelium_sessions(agent_id, host=host)
            if not sessions:
                continue
            for s in sessions:
                key = s.get("key") or s.get("sessionKey")
                if not key:
                    continue
                tokens = s.get("inputTokens") or s.get("totalTokens") or 0
                context_cap = s.get("contextTokens") or 0
                pct = (tokens / context_cap * 100) if context_cap else 0
                if _reset_session(key, host=host):
                    total_reset += 1
                    print(
                        f"  [SETUP] reset {label}:{agent_id} "
                        f"({tokens:,} tokens, {pct:.0f}% of ctx)"
                    )
                else:
                    total_failed += 1
                    print(
                        f"  [SETUP] reset FAILED {label}:{agent_id} key={key}"
                    )

    if total_reset == 0 and total_failed == 0:
        print("  [SETUP] No mycelium-room sessions found to reset")
    elif total_failed:
        print(
            f"  [SETUP] Session reset: {total_reset} ok, "
            f"{total_failed} failed (suite continues)"
        )


@pytest.fixture(scope="session")
def bundle_ctx() -> TestContext:
    _presuite_sanity_checks()

    room_suffix = str(int(time.time()))[-7:]
    room_name = f"{ROOM_PREFIX}-{room_suffix}"
    ctx = TestContext(room_name=room_name)
    detect_environment(ctx)
    _ctx_holder["ctx"] = ctx
    yield ctx
    cleanup(ctx)
    
    # If distributed tests ran, also clean up remote agents
    if _ran_distributed:
        cleanup_distributed()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Track if any distributed tests are being run."""
    global _ran_distributed
    if item.get_closest_marker("distributed"):
        _ran_distributed = True


def _list_leaked_rooms(
    prefixes: tuple[str, ...],
    owned_rooms: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return rooms whose coordination_state is still in ``_LEAKED_STATES``
    and that belong to the current run.

    When ``owned_rooms`` is provided, only rooms whose base name (the part
    before ``:session:``) is in that set are considered.  This prevents
    concurrent test runs from deleting each other's active sessions.

    Uses urllib (stdlib) so this runs even before mycelium_e2e.bundle's http
    helpers have been imported; keeps the fixture cheap and dependency-free.
    """
    try:
        with urllib.request.urlopen(  # noqa: S310 — known internal URL
            f"{BACKEND_URL}/rooms", timeout=5.0
        ) as resp:
            rooms = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []
    leaked: list[dict[str, Any]] = []
    for room in rooms:
        name = room.get("name", "")
        if not any(name.startswith(p) for p in prefixes):
            continue
        if room.get("coordination_state") not in _LEAKED_STATES:
            continue
        # Scope to current run: extract the base room name (strip
        # ``:session:…`` suffix) and check against the owned set.
        base_name = name.split(":session:")[0]
        if owned_rooms is not None and base_name not in owned_rooms:
            continue
        leaked.append(room)
    return leaked


def _delete_room(name: str) -> bool:
    """Best-effort DELETE /rooms/{name}; returns True on 2xx."""
    encoded = urllib.parse.quote(name, safe="")
    req = urllib.request.Request(
        f"{BACKEND_URL}/rooms/{encoded}", method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reap_leaked_sessions(request: pytest.FixtureRequest):
    """After every distributed/matrix-e2e test, find any e2e/dist-e2e rooms
    whose coordination is still in-flight and reap them.

    A room left in ``negotiating`` after a test returns means one of:

    * The test's ``wait_for_mycelium_consensus`` timeout expired before the
      agents/CFN converged, so the test gave up but the backend's coordination
      loop kept polling and agents kept ticking. (Most common — see
      ``distributed_e2e.py`` header comments on the 600s bumps.)
    * The agents crashed/disconnected without finalizing the session.
    * CFN ``decide`` is genuinely stuck (which we surface as a warning rather
      than papering over).

    In all three cases the room is dead weight for the rest of the suite —
    it consumes CFN slots and can starve later tests of LLM/agent capacity
    (we observed test_44 failing immediately after test_41/42/43 leaked).
    Yields control to the test, then logs structured diagnostics and deletes.

    **Scope safety**: only reaps rooms registered in ``ctx._owned_rooms`` by
    the current run.  This prevents concurrent runs from nuking each other's
    active sessions (root cause of the 404-mid-negotiation failures diagnosed
    2026-04-29).
    """
    yield
    relevant_markers = {"distributed", "matrix_e2e", "convergence"}
    test_markers = {m.name for m in request.node.iter_markers()}
    if not (test_markers & relevant_markers):
        return

    ctx = _ctx_holder.get("ctx")
    owned = ctx._owned_rooms if ctx else None

    leaked = _list_leaked_rooms(
        prefixes=("e2e-", "dist-e2e-", "mycelium_room:session:"), owned_rooms=owned,
    )
    if leaked:
        test_name = request.node.name
        print(
            f"\n  [LEAK] {len(leaked)} session(s) still in-flight after "
            f"{test_name} (state in {_LEAKED_STATES}):"
        )
        for room in leaked:
            print(
                f"     - {room.get('name')} "
                f"state={room.get('coordination_state')} "
                f"created_at={room.get('created_at')} "
                f"workspace_id={room.get('workspace_id')}"
            )
            ok = _delete_room(room.get("name", ""))
            print(f"       reaped: {'ok' if ok else 'FAILED'}")
    else:
        test_name = request.node.name
        print(f"\n  [REAPER] {test_name}: no leaked sessions (owned={len(owned) if owned else 0} rooms)")

    # Poll for in-flight agent turns to finish before the next test starts.
    # openclaw agent processes are ephemeral and ignore SIGTERM (see
    # mycelium_e2e.bundle.cleanup_remote_agents for details), so starting
    # the next test while the previous test's turn is still unwinding can
    # cause session-key collisions and LLM quota contention.
    #
    # Only poll for distributed tests — matrix_e2e tests run agents locally
    # in the same gateway and don't need cross-host polling. convergence
    # tests are pure backend and have no agent processes.
    if "distributed" in test_markers:
        counts = wait_for_agents_idle(timeout=20, poll_interval=1.0)
        busy = {h: c for h, c in counts.items() if c > 0}
        if busy:
            print(
                f"  [IDLE-WAIT] agent turns still in-flight after 20s: {busy}"
            )


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    ctx = _ctx_holder.pop("ctx", None)
    if ctx is not None:
        print_results(ctx)

    if not session.config.getoption("--analyze-traces"):
        return
    if not _session_trace_files:
        print("\n[ANALYZE] --analyze-traces set, but no round-trace files were captured this session.")
        return
    _run_trace_analyzer(_session_trace_files)


def _run_trace_analyzer(paths: list[Path]) -> None:
    """Invoke ``tests/analyze_round_traces.py`` on the captured files.

    Run as a subprocess so the analyzer's argparse / printing stays self-
    contained — keeps the conftest's import surface clean and means the
    analyzer can evolve independently without touching this hook.
    """
    import subprocess

    script = Path(__file__).parent / "analyze_round_traces.py"
    if not script.exists():
        print(f"\n[ANALYZE] analyzer script not found at {script}")
        return

    print(
        f"\n[ANALYZE] running {script.name} over {len(paths)} captured file(s)",
        flush=True,
    )
    cmd = [sys.executable, str(script), "--rounds"]
    for p in paths:
        cmd.extend(["--file", str(p)])
    try:
        subprocess.run(cmd, check=False)
    except Exception as exc:  # pragma: no cover — best-effort tooling hook
        print(f"[ANALYZE] failed to run analyzer: {exc}", flush=True)


# ─── CFN round-trace capture (#162) ───────────────────────────────────────────
#
# Wraps every distributed/matrix_e2e/convergence test with a DELETE-before /
# GET-after of the backend's in-memory trace ring buffer
# (/api/internal/coordination/round-traces).  The captured JSON is paired with
# the test outcome and written to ``$MYCELIUM_TRACE_DIR`` (default
# ``~/.mycelium/e2e-logs/traces/``).  The companion analyzer
# ``tests/analyze_round_traces.py`` reads these files; pass ``--analyze-traces``
# to pytest to run it automatically at session end on the files captured this
# session.

_TRACE_ENDPOINT = f"{BACKEND_URL}/internal/coordination/round-traces"
_TRACE_DIR = Path(
    os.environ.get(
        "MYCELIUM_TRACE_DIR",
        os.path.expanduser("~/.mycelium/e2e-logs/traces"),
    )
)
_TRACE_MARKERS = {"distributed", "matrix_e2e", "convergence"}

# Trace files written during this pytest session, in capture order.  Populated
# by ``_capture_round_traces`` and consumed by ``pytest_sessionfinish`` when
# ``--analyze-traces`` is on.
_session_trace_files: list[Path] = []


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--analyze-traces",
        action="store_true",
        default=False,
        help=(
            "After the test session, run tests/analyze_round_traces.py over "
            "the round-trace JSONs captured during this session and print the "
            "summary + aggregate distribution."
        ),
    )


def _delete_trace_buffer() -> bool:
    req = urllib.request.Request(_TRACE_ENDPOINT, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


def _fetch_trace_buffer() -> dict | None:
    try:
        with urllib.request.urlopen(_TRACE_ENDPOINT, timeout=5.0) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Any:
    """Stash the per-phase report on the item so the trace fixture can read
    the test outcome in its finalizer (standard pytest recipe)."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def _capture_round_traces(request: pytest.FixtureRequest):
    """Reset the backend's round-trace ring buffer before each relevant test
    and persist whatever landed in it after the test completes.

    Gated on the same marker set as ``_reap_leaked_sessions`` so unit-style
    tests don't pay the network round-trips.  Independent of the reap
    fixture: we accept that abort-traces produced by reap-driven room
    deletes may be captured by the *next* test's pre-DELETE rather than this
    one's post-GET; that's a known and harmless artefact (those rounds are
    by definition ``decision_path=aborted`` and easy to filter out
    downstream).
    """
    test_markers = {m.name for m in request.node.iter_markers()}
    if not (test_markers & _TRACE_MARKERS):
        yield
        return

    _delete_trace_buffer()  # best-effort; if backend is down the test fails anyway
    yield
    payload = _fetch_trace_buffer()
    if payload is None:
        return

    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    rep_call = getattr(request.node, "rep_call", None)
    rep_setup = getattr(request.node, "rep_setup", None)
    outcome = "passed"
    if rep_setup is not None and rep_setup.failed:
        outcome = "setup_failed"
    elif rep_call is None:
        outcome = "no_call"
    elif rep_call.failed:
        outcome = "failed"
    elif rep_call.skipped:
        outcome = "skipped"

    record = {
        "test": request.node.name,
        "nodeid": request.node.nodeid,
        "outcome": outcome,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend_url": BACKEND_URL,
        "trace_count": payload.get("count", 0),
        "buffer_capacity": payload.get("buffer_capacity"),
        "traces": payload.get("traces", []),
    }
    fname = (
        f"{request.node.name}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}_"
        f"{outcome}.json"
    )
    out_path = _TRACE_DIR / fname
    out_path.write_text(json.dumps(record, indent=2))
    _session_trace_files.append(out_path)
    print(
        f"\n  [TRACE] saved {record['trace_count']} round trace(s) "
        f"-> {out_path}"
    )
