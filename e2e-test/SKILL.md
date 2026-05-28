# pyATS E2E Testing for Mycelium

This skill documents the patterns and conventions used in the Mycelium pyATS E2E test suite, derived from Cisco's pyATS framework, the motific-performance project, and the SMM test suite.

## When to Use

Use this skill when:
- Adding new E2E tests to the Mycelium suite
- Understanding the pyATS test structure (jobs, suites, testcases, datafiles)
- Debugging test failures in the pyATS execution model
- Extending the suite with new test tiers or service integrations

## Core Architecture

The suite follows a four-layer pyATS architecture:

```
┌─────────────────────────────────────────────────────────────┐
│ Job file (jobs/*.py)            ← orchestrates execution    │
│   pyats run job jobs/weekly_e2e_job.py                      │
├─────────────────────────────────────────────────────────────┤
│ Suite file (suites/*.py)        ← thin AEtest script        │
│   CommonSetup → Testcases → CommonCleanup                   │
├─────────────────────────────────────────────────────────────┤
│ Testcase classes (testcases/*.py)  ← reusable test logic    │
│   @aetest.setup / @aetest.test / @aetest.cleanup            │
├─────────────────────────────────────────────────────────────┤
│ Libraries (libs/*.py)           ← API/CLI clients           │
│ Datafiles (data/*.yaml)         ← YAML-driven parameters   │
└─────────────────────────────────────────────────────────────┘
```

## Key Patterns

### 1. Thin Suite Files

Suite files (`suites/*.py`) contain ONLY class declarations that inherit from testcase classes. No test logic in suite files:

```python
from testcases.common_setup_cleanup import MyceliumCommonSetup, MyceliumCommonCleanup
from testcases.core_tests import RoomLifecycle

class CommonSetup(MyceliumCommonSetup):
    pass

class test_01_room_lifecycle(RoomLifecycle):
    pass

class CommonCleanup(MyceliumCommonCleanup):
    pass
```

### 2. Testcase Classes with Steps

Test logic lives in `testcases/*.py` using `@aetest.test` with `steps` for sub-results:

```python
class RoomLifecycle(aetest.Testcase):
    groups = ["core", "sanity"]

    @aetest.test
    def create_room(self, steps, cli, room_name):
        with steps.start("Create room via CLI") as step:
            r = cli.room_create(room_name)
            if not r.ok:
                step.failed(r.error_message)
```

### 3. Parameter Injection from Datafiles

pyATS injects parameters by name from datafiles into test methods. The `testscript.parameters` dict is populated by CommonSetup and available to all testcases:

```python
# In CommonSetup subsection:
testscript.parameters["api"] = MyceliumAPI(base_url=backend_url)
testscript.parameters["cli"] = MyceliumCLI()

# In any testcase — parameters injected automatically:
@aetest.test
def verify(self, api, cli, room_name):
    ...
```

### 4. Environment-Driven Skip Logic

Each testcase uses `@aetest.setup` to check prerequisites via the `env` parameter:

```python
@aetest.setup
def check_prerequisites(self, env):
    if env.skip_llm_tests:
        self.skipped("LLM not available")
    if env.coordination_blocked_reason:
        self.skipped(env.coordination_blocked_reason)
```

### 5. Convergence Base Class Pattern

Multi-agent convergence tests inherit from `_ConvergenceBase` and configure only the scenario:

```python
class ThreeAgentNegotiation(_ConvergenceBase):
    topic = "Sprint planning for Q3 release"
    agent_configs = [
        ("speed-agent", "speed", "Ship fast, cut scope."),
        ("quality-agent", "quality", "Full test coverage."),
        ("cost-agent", "cost", "Minimize spend."),
    ]
```

### 6. Datafile Inheritance with `extends:`

Environment-specific datafiles inherit from base and override only what differs:

```yaml
# data/lab_datafile.yaml
extends: base_datafile.yaml
parameters:
  topology:
    backend:
      base_url: "http://10.0.50.125:8000"
```

### 7. Job File Orchestration

Jobs use `pyats.easypy.run()` with optional `uids` filtering:

```python
from pyats.easypy import run
from pyats.datastructures.logic import Or

testcases_filter = os.getenv("TESTCASES")
if testcases_filter:
    tcs = [t.strip() for t in testcases_filter.split(",")]
    uids = Or("common_setup", *tcs, "common_cleanup")

def main(runtime):
    run(testscript=suite, datafile=datafile, uids=uids)
```

### 8. CommonSetup Subsection Chain

Setup runs in subsection order. Each subsection populates `testscript.parameters`:

1. `initialize_clients` — creates API/CLI client instances
2. `configure_cli` — runs `mycelium init --api-url` and sets default room
3. `detect_environment` — probes backend, CFN, Matrix, sets skip flags
4. `create_test_room` — creates session-scoped test room
5. `presuite_hygiene` — cleans stale sessions, trims agent history
6. `reset_agent_sessions` — gateway RPC reset of negotiation sessions
7. `wait_agents_idle` — polls until agents finish in-flight turns

### 9. Groups for Selective Execution

Each testcase declares `groups` for filtering:

```python
class Synthesis(aetest.Testcase):
    groups = ["core", "llm", "slow"]
```

Run with: `pyats run job ... --groups core` or via `uids` in job files.

## Adding a New Test

1. **Add testcase class** in the appropriate `testcases/*.py` file
2. **Add thin declaration** in the suite file(s) that should include it
3. **Add UID entry** in `data/base_datafile.yaml` under `testcases:`
4. **Set groups** on the class for selective execution
5. **Use steps** for granular sub-results

Example:

```python
# testcases/core_tests.py
class NewFeatureTest(aetest.Testcase):
    groups = ["core"]

    @aetest.test
    def verify_feature(self, steps, api, room_name):
        with steps.start("Check feature endpoint") as step:
            st, data = api.get_json("/new-feature")
            if st != 200:
                step.failed(f"status={st}")
```

```python
# suites/core_suite.py
from testcases.core_tests import NewFeatureTest

class test_23_new_feature(NewFeatureTest):
    pass
```

## Running Tests

```bash
# Full weekly (all tiers)
pyats run job jobs/weekly_e2e_job.py --datafile data/lab_datafile.yaml

# Quick sanity
pyats run job jobs/sanity_job.py

# Specific tier
pyats run job jobs/convergence_job.py

# Specific tests
TESTCASES="test_01_room_lifecycle" pyats run job jobs/core_job.py

# Standalone (no easypy)
python suites/sanity_suite.py --datafile data/local_datafile.yaml

# View HTML report
pyats run job jobs/weekly_e2e_job.py --html-logs && pyats logs view
```

## Library Reference

| Module | Class | Purpose |
|--------|-------|---------|
| `libs/mycelium_api.py` | `MyceliumAPI` | Backend REST client (rooms, memory, sessions, knowledge) |
| `libs/mycelium_cli.py` | `MyceliumCLI` | CLI subprocess wrapper with `CLIResult` |
| `libs/cfn_api.py` | `CfnMgmtAPI` / `CfnNodeSvcAPI` | CFN management + node service clients |
| `libs/matrix_client.py` | `MatrixClient` | Async Matrix Synapse client (httpx) |
| `libs/openclaw.py` | — | Gateway session management, SSH wrappers |
| `libs/environment.py` | `EnvironmentInfo` | Service probing and skip-flag detection |

## Design Decisions

1. **No traditional pyATS testbed YAML** — Mycelium services are not network devices. Configuration uses pyATS datafiles (`parameters:` + `testcases:` sections) following the motific-performance pattern.

2. **Stdlib HTTP for sync clients** — `libs/mycelium_api.py` and `libs/cfn_api.py` use `urllib` (zero-dependency) matching the original harness philosophy. Only Matrix uses `httpx` (async requirement).

3. **Test numbering preserved** — Suite files use `test_NN_*` class names matching the original pytest test numbers for traceability.

4. **Owned-room tracking** — `testscript.parameters["owned_rooms"]` prevents cross-run reaper interference (learned from production failure mode).

5. **Groups over markers** — pyATS uses `groups` (class-level) instead of pytest markers. The mapping: `slow` → `slow`, `llm` → `llm`, `cfn` → `cfn`, `convergence` → `convergence`, `distributed` → `distributed`, etc.
