"""Shared fixtures for the Mycelium end-to-end integration tests."""

from __future__ import annotations

import json
import os
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


@pytest.fixture(scope="session")
def bundle_ctx() -> TestContext:
    # Clean up any stale sessions from previous crashed runs (older than 10 minutes)
    cleanup_stale_sessions(prefix="e2e-", max_age_minutes=10)
    cleanup_stale_sessions(prefix="dist-e2e-", max_age_minutes=10)
    
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


def _list_leaked_rooms(prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return rooms whose name starts with any of ``prefixes`` and whose
    coordination_state is still in ``_LEAKED_STATES``.

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
        if room.get("coordination_state") in _LEAKED_STATES:
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
    """
    yield
    # Only reap for tests that actually touch coordination — gate on the same
    # markers used elsewhere so unit-style tests don't pay the polling cost.
    relevant_markers = {"distributed", "matrix_e2e", "convergence"}
    test_markers = {m.name for m in request.node.iter_markers()}
    if not (test_markers & relevant_markers):
        return

    leaked = _list_leaked_rooms(prefixes=("e2e-", "dist-e2e-"))
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

_TRACE_ENDPOINT = f"{BACKEND_URL}/api/internal/coordination/round-traces"
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
