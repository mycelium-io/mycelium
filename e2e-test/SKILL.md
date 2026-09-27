# pyATS E2E Testing for Mycelium

This skill documents the patterns and conventions used in this repo's pyATS test suite for [Mycelium](https://github.com/mycelium-io/mycelium), a SLIM-native multi-agent coordination platform.

## When to Use

Use this skill when:
- Adding a new test to the PR, nightly, or canary suite
- Understanding the pyATS structure (jobs → suites → testcases → datafiles)
- Debugging a test failure in the pyATS execution model
- Writing a new mechanical stub or live-agent scenario

## Core Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Job file (jobs/*.py)             ← orchestrates execution     │
│   pyats run job jobs/nightly_job.py                            │
├──────────────────────────────────────────────────────────────┤
│ Suite file (suites/*.py)         ← thin AEtest script          │
│   CommonSetup → Testcases → CommonCleanup                      │
├──────────────────────────────────────────────────────────────┤
│ Testcase classes (testcases/*.py)  ← reusable test logic       │
│   @aetest.setup / @aetest.test / @aetest.cleanup                │
├──────────────────────────────────────────────────────────────┤
│ Libraries (libs/*.py)            ← API/CLI clients, stubs      │
│ Datafiles (data/*.yaml)          ← YAML-driven parameters      │
│ Testbeds (testbeds/*.yaml)       ← device topology             │
└──────────────────────────────────────────────────────────────┘
```

Three suites: **PR** (`pr_suite.py`, stack/memory/protocol, no LLM), **nightly** (`nightly_suite.py`, mechanical stub negotiation + hub-and-spoke, no LLM), **canary** (`canary_suite.py`, real cursor-agent multi-episode, informational only — never blocks release). See the repo [README](README.md) for the full suite table.

## Key Patterns

### 1. Thin Suite Files

Suite files (`suites/*.py`) contain only class declarations that inherit from testcase classes — no test logic:

```python
from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.pr_stack import BackendHealth as _BackendHealth

class CommonSetup(MyceliumCommonSetup):
    pass

class BackendHealth(_BackendHealth):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass
```

Testcase classes are imported under a `_Prefixed` alias and re-declared without one — this is what lets pyATS report the plain class name while still reusing logic across suites (e.g. `TwoNodeHubSpoke` is declared once in `nightly_hub_spoke.py` and appears, unmodified, in `nightly_suite.py`).

### 2. Testcase Classes with `uid`

Test logic lives in `testcases/*.py`. Give it a stable `uid` (independent of the class name) so datafiles and CI logs can reference it durably:

```python
class TwoStubRejectionPath(aetest.Testcase):
    """002 — One stub always rejects → session reaches rejected terminal."""
    uid = "nightly_002"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        ...

    @aetest.test
    def session_terminates_on_rejection(self, api: MyceliumAPI, cli: MyceliumCLI):
        ...
```

### 3. Parameter Injection from `testscript.parameters`

`MyceliumCommonSetup` (in `testcases/common_setup_cleanup.py`) populates `testscript.parameters["api"]`, `["cli"]`, `["env"]`, `["room_name"]`, `["owned_rooms"]`. pyATS injects these into any testcase method by argument name:

```python
@aetest.test
def verify(self, api: MyceliumAPI, cli: MyceliumCLI, room_name: str):
    ...
```

`owned_rooms` is a `set()` every testcase should add its own room(s) to — `MyceliumCommonCleanup` deletes everything in it (unless `MYCELIUM_E2E_NO_CLEANUP`/`MYCELIUM_E2E_KEEP_ROOMS` is set). This is the mechanism that prevents cross-run interference; add to it, don't bypass it.

### 4. Environment-Driven Skip Logic

```python
@aetest.setup
def check_prerequisites(self, env):
    if env.skip_llm_tests:
        self.skipped("LLM not available")
```

`env` (an `EnvironmentInfo`, from `libs/environment.py`) is set in `CommonSetup.detect_environment` and carries `backend_reachable`, `slim_reachable`, `skip_llm_tests`.

### 5. Gating on Testbed Topology

Tests that need more than the base `hub` device (hub-and-spoke) call `require_devices` at the top of setup — it skips (not fails) when the loaded testbed doesn't have the device, and is a no-op when no testbed was passed at all (single-host mode):

```python
from testcases.common_setup_cleanup import require_devices

@aetest.setup
def check_topology(self, testscript):
    require_devices(self, testscript, "spoke1", "spoke2")
```

### 6. Mechanical Stub Coordination (nightly suite)

`libs/stub_agent.py`'s `StubAgent` + `run_stubs_until_terminal()` drive a negotiation without any LLM: each stub calls `await`, applies a scripted or `action_fn`-computed accept/reject, and `respond`s. Cross-container variants (`libs/remote_stub.py`'s `RemoteStubAgent`) do the same over `docker exec` for spoke devices.

```python
stub = StubAgent(room, "stub-accept", action="accept", cli=cli)
result = run_stubs_until_terminal(api, [stub_a, stub_b], setup=coord, max_rounds=20, total_timeout=180)
assert result.terminal is not None
```

Two budgets matter and are easy to undersize: `total_timeout` (the client's own patience) and `max_rounds` (how many turns each stub thread will keep answering for). Both need headroom over how long the **mediator** actually needs — see the next pattern.

### 7. Sizing timeouts around the mediator's real step cost, not raw turn latency

The aligner mediates via a NEGMAS SAO mechanism capped at `ALIGNER_MEDIATOR_MAX_STEPS` (backend `app/config.py`, default 20). A raw stub `await`/`respond` round-trip is fast (single-digit seconds), but each **mechanism step** additionally costs the mediator's own LLM calls (`broker()` + `interpret()` in `app/services/mediator.py`, a real Pi-agent session) — measured at roughly 4 raw stub turns per mechanism step. A stalemate scenario (by design, in `TwoStubRejectionPath`) has to run all the way to that step cap before the mediator gives up and emits a `rejected` terminal, so its budget has to be sized against **step** cost, not turn cost:

```python
# ~4 raw turns per mechanism step; 20 steps needs ~80 raw turns.
_REJECTION_MAX_ROUNDS = 45          # own budget — don't reuse a smaller shared constant
_REJECTION_TOTAL_TIMEOUT = 660      # ≈ 20 steps × 4 turns × ~8s/turn, with margin
```

If a rejection-path (or any genuinely-non-converging) test times out with `terminal=None`, check whether the client gave up (or the stub threads ran out of rounds) before the mediator ever reached its step cap — that reads in the backend log as the mediator's own step counter (`"mediator failed to prompt @handle (step N)"` on failure) sitting well below the cap when the room gets torn down. A flood of SLIM `"Session already closed or dropped"` warnings right after is a *symptom* of that premature teardown racing the still-running mediator thread, not a SLIM bug — don't chase it as one.

### 8. Datafile Inheritance with `extends:`

```yaml
# data/nightly_datafile.yaml
extends: base_datafile.yaml
parameters:
  room_prefix: "qa-coord-fresh"
  max_failures: 5
```

`base_datafile.yaml` holds every shared parameter (topology, timeouts, room prefix); each suite's datafile only overrides what differs.

### 9. Job File Orchestration

```python
from jobs._common import get_datafile, get_project_root, install_job_sigint_cleanup, resolve_backend_url

def main(runtime):
    root = get_project_root()
    datafile = get_datafile(default="nightly_datafile.yaml")
    install_job_sigint_cleanup(resolve_backend_url(datafile))
    for suite_name in ("pr_suite.py", "nightly_suite.py"):
        run(testscript=os.path.join(root, "suites", suite_name), datafile=datafile)
```

`nightly_job.py` runs both `pr_suite.py` and `nightly_suite.py` in sequence (the PR suite gates the nightly suite). `install_job_sigint_cleanup` registers a SIGINT handler that still deletes owned rooms on Ctrl-C.

### 10. Groups for Selective Execution

```python
class SkillCrossChannelReturnTrip(_DistributedBase):
    groups = ["hub_and_spoke", "cross_channel", "llm", "slow"]
```

Filter with `MYCELIUM_E2E_GROUPS` (comma-separated, OR'd — see `jobs/_common.py`'s `groups_filter_from_env`) or pyATS's own `--groups` flag.

## Adding a New Test

1. Add the testcase class to the right `testcases/{pr,nightly,canary}_*.py` file, with a `uid`.
2. Add a thin re-declaration in the suite file(s) it belongs in (`pr_suite.py`, `nightly_suite.py`, or `canary_suite.py`).
3. If it needs its own timeout/round budget, size it against real step/turn cost (pattern 7) — don't silently reuse a module-level constant sized for a different scenario.
4. Set `groups` if it should be selectively filterable.
5. Run it directly first: `pyats run job jobs/<suite>_job.py --testbed-file testbeds/local.yaml`.

## Library Reference

| Module | Class/Function | Purpose |
|--------|-----------------|---------|
| `libs/mycelium_api.py` | `MyceliumAPI` | Backend REST client (rooms, memory, sessions, agent-context) |
| `libs/mycelium_cli.py` | `MyceliumCLI` | CLI subprocess wrapper; handles the `MYCELIUM_LOCAL_WRITE_UID` switch |
| `libs/environment.py` | `EnvironmentInfo`, `detect_environment` | Service probing and skip-flag detection |
| `libs/coordination_flow.py` | `setup_coordination`, `poll_for_terminal_state`, `wait_for_coordination_join` | Room + agents + opening positions; terminal-state/join polling |
| `libs/stub_agent.py` | `StubAgent`, `run_stubs_until_terminal` | Mechanical single-process stub negotiation |
| `libs/remote_stub.py` | `RemoteStubAgent`, `run_remote_stubs_until_terminal` | Same, driven over `docker exec` on spoke devices |
| `libs/agent_pools.py` | — | Provisioner-backed agent pool for `hub_and_spoke_tests.py`-style scenarios |
| `libs/provisioners/` | `Provisioner`, `get_provisioner` | Adapter-agnostic (openclaw/cursor/hermes) create/wake/cleanup protocol |
| `libs/host_exec.py` | `execute` | Local vs. `docker exec` command dispatch by device `custom.transport` |

## Design Decisions

1. **No traditional pyATS testbed for single-host runs** — `testbeds/local.yaml` exists only to satisfy the pyATS schema; topology-dependent tests key off `testscript.parameters["testbed_devices"]`, not a real device connection, and skip cleanly when it's empty.
2. **Stdlib-only sync HTTP** — `libs/mycelium_api.py` uses `urllib`, zero extra dependency.
3. **`uid` over class name for identity** — testcase `uid`s (unprefixed for the PR suite, `nightly_*`/`canary_*` for the others) are what CI logs and datafiles reference; class names can be re-aliased per suite without breaking that.
4. **Owned-room tracking** — `testscript.parameters["owned_rooms"]` is the only thing `MyceliumCommonCleanup` trusts; a testcase that creates a room outside of it leaks state across runs.
5. **The canary suite never blocks** — `canary_job.py`/`weekly-e2e.yaml` treat every failure as informational (`max_failures: 0`, `continue-on-error: true`). It exists to catch live-LLM compatibility drift, not to gate merges.
6. **Timeouts sized against the mediator's real cost** — see pattern 7 above. This was the root cause the last time a nightly-suite stalemate test looked like a SLIM bug and wasn't.
