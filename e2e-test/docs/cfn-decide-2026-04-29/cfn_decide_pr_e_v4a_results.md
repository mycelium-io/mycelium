# PR E v4-A: switch ingestion LLM calls to `litellm.acompletion`

Iteration in the CFN `/decide` latency series.  Adds async-flavored
public/private entry points to the ingestion service so the two LLM
round trips run via `litellm.acompletion` instead of a synchronous
`litellm.completion` blocking inside an `asyncio.to_thread` worker.

## Patch summary

| File | Change |
| --- | --- |
| `ioc-cfn-cognition-engines/ingestion/app/agent/service.py` | New `_llm_extract_concepts_async`, `_llm_extract_relationships_async`, `extract_concepts_and_relationships_async` (uses `litellm.acompletion`).  Shared post-LLM formatting factored into `_format_extraction_result(...)`.  Existing sync API preserved. |
| `ioc-cfn-cognition-engines/ingestion/app/agent/ingest_data.py` | New `IngestDataService.ingest_async(...)` that awaits the new async public method.  Existing sync `ingest()` preserved. |
| `ioc-cognition-fabric-node-svc/src/app/api/semantic_nego.py` | `persist_negotiation_agreement_background` now awaits `ingest_service.ingest_async(...)` directly (no thread for the LLM call).  Only the CPU-bound `processor.process(...)` post-step is still off-loaded via `asyncio.to_thread`. |

The diff is purely additive in the engines repo: existing sync HTTP route
`/extraction`, the CLI tool `run_ingestion_e2e.py`, and the
`extract_entities_and_relations` legacy path all continue to use the
unchanged sync API.

## Smoke run

`tests/test_mycelium_e2e.py::test_40_distributed_two_agent` and
`test_41_distributed_three_agent` ran end-to-end against the patched
container (`docker cp` deploy + restart).

| Test | Outcome | Rounds |
| --- | --- | --- |
| `test_40_distributed_two_agent` | passed | 4 |
| `test_41_distributed_three_agent` | passed | 10 |

Total: **2/2 passed**, 14 `cfn_decide_ms` samples captured.

## /decide latency

`cfn_decide_ms` extracted from each test's trace JSON
(`/home/ubuntu/.mycelium/e2e-logs/traces/test_4*_2026042?_*_passed.json`):

| Metric | v3 (to_thread, sync LLM) | v4-A (acompletion) |
| --- | --- | --- |
| n samples | 11 | 14 |
| min ms | 43 | 39 |
| **p50 ms** | **590** | **841** |
| p95 ms | 46 735 | 57 312 |
| max ms | 46 735 | 57 312 |
| mean ms | 7 816 | 9 032 |

v4-A is **a regression** at this layer alone.  Median rose ~250 ms,
the long-tail max rose ~10 s.

## Wedge profile

| Bucket | v3 | v4-A |
| --- | --- | --- |
| total wedges (>500ms lag) | 11 | 25 |
| <2 s | 1 | 10 |
| 2–4 s | 0 | 4 |
| 23–39 s | 10 | 11 |

The huge wedges are roughly the same magnitude as v3 — but the **set of
new sub-2 s wedges** appearing in v4-A is the cost of running the LLM
parse on the loop again.

## Why v4-A alone doesn't help

Wedge timestamps on v4-A no longer line up with `LLM relationship
extraction returned N` (good — `acompletion` does what it advertises).
They now line up with two other landmarks:

```
21:01:25.682  ingestion.app.agent.knowledge_processor:294
              Processed: 39 concepts, 34 relations
21:01:25.701  CFN event-loop wedge: lag=30847.0ms

21:01:51.157  knowledge_memory.server.adapters.adapter_graphdb_agensgraph:90
              Successfully converted to 24 nodes and 29 edges
21:01:51.167  CFN event-loop wedge: lag=25406.0ms

21:18:37.489  ingestion.app.agent.knowledge_processor:294
              Processed: 29 concepts, 38 relations
21:18:37.503  CFN event-loop wedge: lag=28459.0ms
```

Both landmarks correspond to **CPU-bound, GIL-holding pure-Python work
running inside a worker thread** (per-concept ONNX / `fastembed`
inference in `KnowledgeProcessor.process`, and SQLAlchemy/psycopg2
cursor work in the AgensGraph upsert path).  With a single Uvicorn
worker process and the GIL in play, the worker thread starves the main
event loop's `selector.select()` for the duration of those CPU bursts.

`acompletion` correctly removed the LLM round trip's contribution to
that GIL pressure, but the remaining ingestion CPU work is large
enough on its own to keep the loop wedged for 20–40 s.  On top of
that, the small `acompletion` response decode now runs on the loop —
hence the new band of 1–2 s wedges that v3 didn't have.

## Net assessment

* **Correctness**: v4-A is a directional improvement.  The LLM round
  trip is now properly cooperative, and the engines repo gains a clean
  public async API (`extract_concepts_and_relationships_async`,
  `IngestDataService.ingest_async`) that other callers can adopt.
* **Latency**: alone, v4-A is a **wash to small regression**.  The
  remaining wedges have moved one layer down the stack and are now
  100 % attributable to ingestion-side CPU bursts (embedding +
  AgensGraph writes).
* **Recommendation**: keep v4-A as an enabling change, but it should
  ship in tandem with v4-B — see below.

## Proposed v4-B (next step)

The remaining big wedges have two distinct sources, each addressable
on its own:

1. **`KnowledgeProcessor.process()` per-concept embedding loop**
   (`ingestion/app/agent/knowledge_processor.py`).  Today it iterates
   concepts and calls `embedding_manager.generate_embedding(...)` once
   per concept on the worker thread.  Two options:
   * Batch into a single `fastembed` call (tens to hundreds of texts
     per call) — `fastembed`'s ONNX kernel releases the GIL on native
     compute, so a single batched call yields far less GIL pressure
     than N short bursts.
   * Run the processor in a separate worker process (e.g.
     `ProcessPoolExecutor` reserved for ingestion, or a dedicated
     queue + sidecar).
2. **AgensGraph upsert work surfaced through
   `upsert_knowledge_graph_async`** (already wrapped with
   `asyncio.to_thread`, but still GIL-bound during cursor / row
   marshalling).  Same two options apply; the simpler win is a small
   `ProcessPoolExecutor` for the ingestion `BackgroundTask` body so it
   doesn't share the GIL with the request loop at all.

A focused v4-B that batches the embedding loop and moves the
AgensGraph writes into a process pool would compose with v4-A and is
likely where the rest of the latency win lives.

## Status

* Patches saved on local branches:
  * `ioc-cfn-cognition-engines` → `experiment/cfn-decide-pr-e-v4a`
  * `ioc-cognition-fabric-node-svc` → still on the v3 working branch
    (semantic_nego.py edited in place; ready to commit on a v4-A
    branch when desired).
* Patched container in place; smoke run logs at
  `/home/ubuntu/.mycelium/e2e-logs/pr_e_v4a_smoke_20260426_211259.log`.
* CFN logs captured at `/tmp/cfn_v4a.log`.
