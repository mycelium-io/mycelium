# mycelium-e2e-test

End-to-end and distributed test harness for [Mycelium](https://github.com/mycelium-io/mycelium).

This repository is an **operator-side** harness: the tests drive a running
Mycelium backend (and, for distributed tests, OpenClaw agents on multiple
machines) over its public HTTP and CLI surfaces. None of the backend or CLI
code lives here — it is exercised externally.

## Layout

```
mycelium_e2e/                 Test-harness package
  bundle.py                   TestContext, env detection, cleanup helpers
  config.py                   BACKEND_URL, ROOM_PREFIX, etc. (env-driven)
  distributed_e2e.py          Distributed scenario implementations
  matrix_e2e.py               Matrix-channel scenario implementations
  cross_channel_e2e.py        Cross-channel scenario implementations
  main.py                     Standalone CLI entry point

tests/
  conftest.py                 Shared fixtures (bundle_ctx, leak reaper,
                              CFN round-trace capture)
  test_mycelium_e2e.py        ~50 numbered tests (test_00 .. test_48)
  analyze_round_traces.py     Standalone analyzer for captured trace JSONs
  README.md                   Per-test inventory and prerequisites

scripts/
  cleanup-sessions.sh         Reap stale negotiating sessions
  refresh-matrix-tokens.sh    Rotate Matrix access tokens across nodes

pytest.ini                    Marker registry + testpaths
requirements-test.txt         pytest>=8.0  (otherwise stdlib-only)
```

## Quick start

```bash
git clone https://github.com/sfph/mycelium-e2e-test.git
cd mycelium-e2e-test
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt

# Point at a running Mycelium backend (default is http://localhost:8000)
export MYCELIUM_BACKEND_URL=http://oclw4:8000

# Matrix tests need access tokens — never commit these. One env var per agent:
#   MATRIX_TOKEN_<AGENT_UPPER_WITH_UNDERSCORES>
export MATRIX_TOKEN_AGENT_ALPHA=syt_...
export MATRIX_TOKEN_AGENT_BETA=syt_...
export MATRIX_TOKEN_AGENT_GAMMA=syt_...
# (use scripts/refresh-matrix-tokens.sh to rotate)

# Run only the fast subset
pytest -m "not slow"

# Run the full distributed matrix
pytest -m distributed
```

See `tests/README.md` for a per-test inventory and the marker glossary.

## CFN round-trace instrumentation

Tests marked `distributed`, `matrix_e2e`, or `convergence` automatically
scrape the backend's in-memory round-trace ring buffer
(`/api/internal/coordination/round-traces`) before and after each test, and
write a JSON file per test under
`$MYCELIUM_TRACE_DIR` (default `~/.mycelium/e2e-logs/traces/`).

Each trace decomposes a CFN negotiation round into:

| Field | Meaning |
|---|---|
| `elapsed_ms` | Total round wall time (open → close) |
| `last_reply_received_ms` | When the final agent reply landed |
| `cfn_decide_started_ms` | When `/decide` was invoked |
| `cfn_decide_ms` | Duration of the `/decide` call itself |
| `decision_path` | `all_replied` · `watchdog_fired` · `hard_cap` · `aborted` |
| `per_agent[].first_response_ms` | Per-agent reply latency |
| `per_agent[].was_synthesised` | True when the watchdog filled in a reject |

This lets observers tell *agent latency* apart from *CFN decide latency*,
which a single elapsed-time field cannot answer.

### Analyzer

`tests/analyze_round_traces.py` aggregates one or more captured JSONs:

```bash
# Most recent capture (per-test summary + aggregate distribution)
python tests/analyze_round_traces.py

# Per-round breakdown table too
python tests/analyze_round_traces.py --rounds

# Last N captures
python tests/analyze_round_traces.py --last 5

# Pattern within the trace dir
python tests/analyze_round_traces.py --glob 'test_41_*.json'

# Explicit set
python tests/analyze_round_traces.py --file a.json --file b.json

# Machine-readable
python tests/analyze_round_traces.py --json
```

### Run analyzer automatically after pytest

Pass `--analyze-traces` to pytest and the analyzer runs at session end on
exactly the files captured during that session:

```bash
pytest -m distributed --analyze-traces
```

## Backend requirements

The instrumentation endpoint and decomposed timing fields require a Mycelium
backend that includes the changes from
[mycelium-io/mycelium#162](https://github.com/mycelium-io/mycelium/issues/162)
(round trace instrumentation + decide-latency decomposition). With an older
backend the trace capture fixture will get back empty payloads but the suite
itself still runs.

## Prerequisites

| Tier | Needs |
|---|---|
| Local tests (00–32) | Mycelium backend, Matrix Synapse, IOC/CFN services |
| Matrix E2E (30–32) | OpenClaw gateway running locally |
| Distributed (40–48) | OpenClaw agents on additional hosts (e.g. oclw3, oclw5) reachable from the backend host, with valid Matrix tokens |

See `tests/README.md` § *Prerequisites* and § *Troubleshooting* for details.
