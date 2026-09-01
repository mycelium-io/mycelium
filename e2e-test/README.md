# mycelium-e2e-test

pyATS-based end-to-end test suite for [Mycelium](https://github.com/mycelium-io/mycelium), a multi-agent coordination platform.

This repository is an **operator-side** harness: tests drive a running Mycelium backend (and, for hub_and_spoke tests, OpenClaw agents on multiple machines) over its public HTTP and CLI surfaces.

## Architecture

The suite follows pyATS conventions with a hub-and-spoke design:

```
jobs/                           Easypy job files (orchestration)
  weekly_e2e_job.py             Full weekly long-running E2E
  core_job.py                   Core tests only
  convergence_job.py            Multi-agent convergence
  distributed_job.py            Cross-device hub_and_spoke tests
  _common.py                    Shared job utilities

suites/                         Thin AEtest scripts (class declarations)
  weekly_full_suite.py          All 42 tests
  core_suite.py                 Tests 01-14, 22
  convergence_suite.py          Tests 15-21
  distributed_suite.py          Tests 30-49

testcases/                      Reusable AEtest testcase classes
  common_setup_cleanup.py       CommonSetup/Cleanup (env detection, hygiene)
  core_tests.py                 Rooms, memory, CLI, sessions, search
  cfn_tests.py                  IOC/CFN integration
  matrix_tests.py               Matrix communication
  convergence_tests.py          Simulated multi-agent convergence
  distributed_tests.py          Real agent cross-device tests
  openclaw_tests.py             Skill verification
  cross_channel_tests.py        Cross-channel memory isolation

libs/                           Shared libraries
  mycelium_api.py               Backend HTTP REST client
  mycelium_cli.py               CLI subprocess wrapper
  cfn_api.py                    CFN management + node-svc client
  matrix_client.py              Matrix Synapse async client
  openclaw.py                   OpenClaw gateway helpers
  environment.py                Environment detection & health probes

data/                           pyATS datafiles (YAML config)
  base_datafile.yaml            Shared parameters (topology, timeouts)
  lab_datafile.yaml             Lab topology overlay (oclw3/4/5)
  local_datafile.yaml           Localhost topology overlay
  weekly_datafile.yaml          Full weekly suite UIDs (extends lab)
  core_datafile.yaml            Core suite UIDs (extends lab)
  distributed_datafile.yaml     Distributed suite UIDs (extends lab)

scripts/                        Operator utility scripts
docs/                           Historical investigation docs
```

## Quick Start

### Install

```bash
# Create venv and install dependencies
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Run

```bash
# Core tests against lab (default datafile includes lab topology)
pyats run job jobs/core_job.py

# Full weekly E2E (long-running, all tiers)
pyats run job jobs/weekly_e2e_job.py

# Distributed tests only
pyats run job jobs/distributed_job.py

# Specific tests via TESTCASES filter
TESTCASES="test_01_room_lifecycle, test_02_multi_agent_memory" \
    pyats run job jobs/weekly_e2e_job.py

# With HTML report
pyats run job jobs/weekly_e2e_job.py --html-logs

# View logs from last run
pyats logs view
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MYCELIUM_BACKEND_URL` | `http://localhost:8000` | Backend base URL |
| `CFN_MGMT_URL` | `http://localhost:9000` | CFN management plane |
| `CFN_SVC_URL` | `http://localhost:9002` | CFN node service |
| `MATRIX_URL` | `http://localhost:8008` | Matrix Synapse |
| `OCLW3_IP` | `10.0.50.171` | Remote host (claire-agent) |
| `OCLW4_IP` | `10.0.50.125` | Hub host (backend + local agents) |
| `OCLW5_IP` | `10.0.50.142` | Remote host (oclw5-agent) |
| `MATRIX_TOKEN_AGENT_ALPHA` | — | Matrix access tokens per agent |
| `MATRIX_SHARED_SECRET` | — | Synapse admin registration secret |
| `E2E_MYCELIUM_ROOM` | `mycelium_room` | Shared Mycelium room name |
| `MYCELIUM_DATAFILE` | `base_datafile.yaml` | Override datafile from env |
| `TESTCASES` | — | Comma-separated test filter |

## Test Tiers

| Tier | Tests | Groups | Requirements |
|------|-------|--------|-------------|
| **Sanity** | 01-04, 06c, 11, 22 | `core`, `sanity` | Backend only |
| **Core** | 01-14, 22 | `core` | Backend + CFN + LLM (some) |
| **CFN** | 08-10 | `cfn` | CFN stack |
| **Matrix** | 07 | `matrix` | Synapse |
| **Convergence** | 15-21 | `convergence` | Backend + CFN + LLM |
| **Local-Real** | 30-32 | `local_e2e` | OpenClaw + Matrix + local agents |
| **Distributed** | 40-49 | `hub_and_spoke` | Remote agents on oclw3/oclw5 |
| **OpenClaw** | 50-51 | `openclaw` | OpenClaw with mycelium adapter |
| **Cross-Channel** | 60 | `cross_channel` | LLM + Matrix |

## pyATS Concepts

- **Job file**: Orchestrates which suites run and with what parameters
- **Suite file**: Thin AEtest script with CommonSetup + Testcases + CommonCleanup
- **Testcase class**: Reusable test logic with `@aetest.setup/test/cleanup`
- **Datafile**: YAML-driven parameters injected into tests at runtime
- **Steps**: Fine-grained sub-results within each test for debuggability
