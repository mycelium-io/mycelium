# mycelium-e2e-test

pyATS-based end-to-end test suite for [Mycelium](https://github.com/mycelium-io/mycelium), a SLIM-native multi-agent coordination platform.

This is an **operator-side** harness: tests drive a running Mycelium backend over its public HTTP and CLI surfaces. Nothing here modifies Mycelium's own source — it's a black-box consumer of the backend API, the `mycelium` CLI, and (for the canary suite) real LLM-backed cursor agents.

## Architecture

```
jobs/                            Easypy job files (orchestration)
  pr_job.py                      PR checks only — runs on every PR (~10 min)
  nightly_job.py                 PR checks + stub coordination — nightly/pre-release (~30 min)
  canary_job.py                  Live agent, manual/weekly (informational)
  _common.py                     Shared job utilities (datafile/testbed/env resolution)

suites/                          Thin AEtest scripts (class declarations only)
  pr_suite.py                    Stack health, memory, protocol
  nightly_suite.py               Stub coordination + hub-and-spoke
  canary_suite.py                Live multi-episode canary
  minimal_test.py                Smoke test for the pyATS subprocess itself

testcases/                       Reusable AEtest testcase classes
  common_setup_cleanup.py        CommonSetup/Cleanup (client init, room hygiene)
  pr_stack.py                    Backend health, room lifecycle, CLI basics
  pr_memory.py                   Memory CRUD, briefing contract, search
  pr_protocol.py                 Session API shape, await/respond, agent-context
  nightly_stub_coord.py          Mechanical two-stub negotiation scenarios
  nightly_hub_spoke.py           Cross-container (hub + spoke) stub coordination
  canary_live_episode.py         Real cursor-agent multi-episode canary
  hub_and_spoke_tests.py         Not currently wired into any suite — see note below

libs/                            Shared libraries
  mycelium_api.py                Backend HTTP REST client
  mycelium_cli.py                CLI subprocess wrapper (handles the local-write uid switch)
  environment.py                 Service probing and skip-flag detection
  coordination_flow.py           setup_coordination() — room + agents + opening positions;
                                  poll_for_terminal_state(), wait_for_coordination_join()
  stub_agent.py                  Mechanical StubAgent + run_stubs_until_terminal()
  remote_stub.py                 RemoteStubAgent — stub driven over docker exec (spokes)
  agent_pools.py                 Provisioner-backed agent pool for multi-device tests
  provisioners/                  Adapter-agnostic provisioner protocol (openclaw/cursor/hermes)
  host_exec.py                   Local vs. docker-exec command dispatch

data/                            pyATS datafiles (YAML config, `extends:` base)
  base_datafile.yaml             Shared parameters (topology, timeouts, room prefix)
  pr_datafile.yaml               PR suite overlay
  nightly_datafile.yaml          Nightly suite overlay
  canary_datafile.yaml           Canary suite overlay (room rotation, episode cap)

testbeds/                        pyATS testbed YAML (device topology)
  local.yaml                     Single host — CLI and backend on the same machine
  compose.yaml                   Hub (local) + spoke1/spoke2 via `docker exec` (CI)
  lab.yaml                       Hub + spoke1/spoke2 via SSH (oclw4/oclw3/oclw5)

scripts/                         Operator utility scripts
  cleanup-sessions.sh            Clean stale negotiating sessions / remote agent processes
  cursor_exec.sh                 Exec driver for `mycelium await --loop --exec` (canary suite)

infra/
  compose.spokes.yaml            Docker Compose for the two spoke containers (nightly suite)

tests/unit/                      Offline unit tests for libs/ and jobs/_common.py (pytest)
docs/                            Historical investigation writeups (not living docs)
```

**Note on `testcases/hub_and_spoke_tests.py`:** this file holds real local/distributed negotiation scenarios (two/three-agent, architecture decisions, resource allocation, cross-device) written against `libs/provisioners`. It is not currently imported by any suite — the suite that used to wire it in (`hub_and_spoke_suite.py`) imported a module name that no longer exists and was removed. The scenarios themselves may be worth reviving as canary episodes or a new suite; treat this file as reference material, not as something CI exercises today.

## Suites

| Suite | Job | UIDs | Real LLM? | Blocks release? |
|-------|-----|------|-----------|------------------|
| **PR** | `pr_job.py` | `BackendHealth`, `RoomLifecycle`, `CLIBasics`, `MemoryCRUD`, `BriefingContract`, `MemorySearch`, `SessionAPIShape`, `RespondWithoutAwait`, `RoomDeleteIdempotent`, `AgentContextEndpointShape` | No | Yes — every PR |
| **Nightly** | `nightly_job.py` (runs `pr_suite.py` then `nightly_suite.py`) | `nightly_001`–`006` (`TwoStubHappyPath`, `TwoStubRejectionPath`, `CounterOfferChain`, `RespondWithoutTurnRejected`, `CrossEpisodeMemory`, `MultiSessionResponseRate`), `nightly_HUB01`/`HUB02` | No — mechanical stubs (opt-in real cursor via `MYCELIUM_E2E_USE_CURSOR_STUBS=1`) | Yes — nightly + pre-release |
| **Canary** | `canary_job.py` | `canary_E01`, `canary_E02` | Yes — real cursor agent by default | No — informational only |

The PR and nightly suites need no LLM credentials at all; the canary suite needs `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` and, for the cursor adapter, `CURSOR_API_KEY`.

`nightly_HUB01`/`HUB02` (in `nightly_hub_spoke.py`) require `spoke1`/`spoke2` devices — they skip automatically on `testbeds/local.yaml` and only run for real on `testbeds/compose.yaml` (CI) or `testbeds/lab.yaml`.

## Quick Start

### Install

```bash
uv sync
# or: python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

### Run

There is no wrapper script — pick the job and testbed explicitly:

```bash
# PR checks — fast, no LLM, single host
pyats run job jobs/pr_job.py --testbed-file testbeds/local.yaml

# PR checks + nightly stub coordination, hub + spokes via docker exec
pyats run job jobs/nightly_job.py --testbed-file testbeds/compose.yaml

# Canary — live agent, needs LLM credentials, informational only
pyats run job jobs/canary_job.py --testbed-file testbeds/local.yaml

# Against the lab (oclw4) instead of localhost
MYCELIUM_BACKEND_URL=http://10.0.50.125:8000 \
    pyats run job jobs/nightly_job.py --testbed-file testbeds/lab.yaml

# Override the datafile explicitly rather than relying on the job's default
pyats run job jobs/pr_job.py --testbed-file testbeds/local.yaml --datafile data/pr_datafile.yaml

# Unit tests (offline, no backend needed)
uv run pytest tests/unit -q
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MYCELIUM_BACKEND_URL` | `http://localhost:8000` | Backend base URL |
| `MYCELIUM_DATAFILE` | `base_datafile.yaml` | Override datafile from env |
| `MYCELIUM_E2E_RUNTIME` | auto-detected | `local` or `lab` — selects the default testbed when none is passed |
| `MYCELIUM_E2E_NO_CLEANUP` | unset | Skip all room teardown (setup + cleanup) |
| `MYCELIUM_E2E_KEEP_ROOMS` | unset | Skip only cleanup's room deletion |
| `MYCELIUM_E2E_USE_CURSOR_STUBS` | unset | Nightly hub-and-spoke: swap mechanical stub replies for real cursor-agent ones |
| `MYCELIUM_CANARY_ROOM` | `api-design-review` | Canary suite room name |
| `MYCELIUM_CANARY_ADAPTER` | `cursor` | Canary suite agent adapter |
| `MYCELIUM_LOCAL_WRITE_UID` | unset | Run local-write CLI commands (`agent create`, `engine create`) as this uid, to match the backend container's fixed uid — see `libs/mycelium_cli.py` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | unset | Live LLM credentials — the canary suite skips without them |
| `CURSOR_API_KEY` / `CURSOR_MODEL` | unset | cursor-agent CLI credentials (canary suite's default adapter; nightly's hub-and-spoke opt-in) |
| `OCLW3_IP` / `OCLW4_IP` / `OCLW5_IP` | lab IPs | Lab testbed device addresses |
| `SSH_USER` / `SSH_KEY_PATH` | `ubuntu` / `~/.ssh/ioc.pem` | Lab testbed SSH credentials |

## CI

Two workflows:

- **`.github/workflows/e2e.yml`** — PR suite on every push/PR to a non-main branch; PR + nightly suite at 05:00 UTC; also triggerable via `workflow_dispatch` or cross-repo `repository_dispatch` from the Mycelium repo (`mycelium-pr-test`/`mycelium-nightly`). Can build Mycelium from source (pass a `mycelium_ref`) instead of installing the latest release.
- **`.github/workflows/weekly-e2e.yaml`** — canary suite, manual `workflow_dispatch` only (the weekly cron is currently commented out). Never blocks — `continue-on-error: true`.

Both workflows start a real `mycelium` backend (Docker) on the runner before running any suite.

## pyATS Concepts

- **Job file** (`jobs/*.py`): orchestrates which suite(s) run and with what datafile/testbed
- **Suite file** (`suites/*.py`): thin `CommonSetup + Testcases + CommonCleanup` declaration, no test logic
- **Testcase class** (`testcases/*.py`): the actual test logic, `@aetest.setup/test/cleanup`
- **Datafile** (`data/*.yaml`): YAML parameters injected into `testscript.parameters`, inherited via `extends:`
- **Testbed** (`testbeds/*.yaml`): device topology (hub/spoke1/spoke2) — governs which tests apply
