# PR E v4-B (part 1: batched embeddings) results

Stacks on top of v4-A.  Two-step plan was:

1. **Batch the per-concept embedding loop** in
   `KnowledgeProcessor.generate_embeddings_for_concepts(...)` into a
   single `fastembed.TextEmbedding.embed(...)` call.
2. **Process-isolate** the ingestion `BackgroundTask` (still pending —
   see "Where the remaining wedges live" below for why and what shape
   it should take).

This document covers step 1, which has been implemented, deployed, and
smoke-tested.  Step 2 is recommended as a separate follow-up.

## Patch summary

| File | Change |
| --- | --- |
| `ioc-cfn-cognition-engines/ingestion/app/agent/knowledge_processor.py` | New `EmbeddingManager.generate_embeddings_batch(texts: List[str])` issues a single ONNX call for the whole list (preserving `None` for empty inputs).  `KnowledgeProcessor.generate_embeddings_for_concepts(...)` now calls it once per `process()` invocation instead of looping `generate_embedding(name)` per concept. |

Branch: `experiment/cfn-decide-pr-e-v4b` (engines repo).
CFN-svc unchanged from v4-A.

## Smoke run

`tests/test_mycelium_e2e.py::test_40_distributed_two_agent` and
`test_41_distributed_three_agent` ran end-to-end against the patched
container (v4-A patches still in place).

| Test | Outcome | Rounds |
| --- | --- | --- |
| `test_40_distributed_two_agent` | passed | 4 |
| `test_41_distributed_three_agent` | passed | 16 |

Total: **2/2 passed**, 20 `cfn_decide_ms` samples captured.
Smoke log: `/home/ubuntu/.mycelium/e2e-logs/pr_e_v4b_batch_smoke_20260426_232117.log`.

## /decide latency vs. prior iterations

Latencies are `cfn_decide_ms` extracted from the test trace JSON.

| Metric | v3 (to_thread, sync LLM) | v4-A (acompletion only) | v4-B-batch (acompletion + batched embeddings) |
| --- | ---:| ---:| ---:|
| n samples | 11 | 14 | 20 |
| min ms | 43 | 39 | 49 |
| **p50 ms** | 590 | 841 | **624** |
| **p95 / max ms** | 46 735 | 57 312 | **30 774** |
| **mean ms** | 7 816 | 9 032 | **5 574** |
| **wedges (>500 ms lag)** | 11 | 25 | **13** |

Read against v4-A:

* p50 dropped from 841 ms back near v3 levels (624 ms).
* Max latency dropped from 57.3 s to 30.8 s (**−46%**).
* Mean dropped from 9.0 s to 5.6 s (**−38%**).
* Wedge count dropped from 25 to 13 (almost halved).

Read against v3:

* p50 essentially flat (590 → 624 ms).
* Max latency dropped from 46.7 s to 30.8 s (**−34%**).
* Mean dropped from 7.8 s to 5.6 s (**−29%**).
* Wedge count comparable (11 → 13), but with the LLM-call wedger
  cleanly removed (acompletion) and the per-concept embedding loop
  collapsed into one batched ONNX call.

Both axes — peak and mean — moved in the right direction.

## Where the remaining wedges live

The 13 wedges in this run break down as:

| Bucket | Count |
| --- | ---:|
| 0.5 – 2 s | 5 |
| 2 – 4 s | 3 |
| ≥ 10 s | 5 |

The 5 large wedges (25.6 s, 27.1 s, 27.3 s, 30.8 s, 35.4 s) all fire
1–10 ms after `adapter_graphdb_agensgraph: Successfully converted to N
nodes and M edges`, immediately before the `upsert_knowledge_graph_async`
psycopg2 round trip.

Stack snapshots taken at wedge time show only uvicorn / starlette
`await` boilerplate frames (`run_asgi`, `BaseHTTPMiddleware.coro`,
`registration.start_heartbeat`).  No application Python frame is
visible.  This is the classic signature of **a C extension holding the
GIL on a worker thread** — in this case the synchronous SQLAlchemy /
psycopg2 path inside `upsert_knowledge_graph_async` (which is itself
wrapped in `asyncio.to_thread`, but the GIL is still single-process).

Net: ingestion CPU work is now narrowly attributable to AgensGraph
writes plus the post-LLM Cypher row marshalling that runs ahead of
them.  The embedding loop is no longer a wedger.

## Recommendation: v4-C (process isolation for ingestion)

To remove the remaining 25–35 s wedges we have to take the AgensGraph
write off the FastAPI process's GIL.  Three viable shapes, in
increasing scope:

1. **Dedicated single-worker thread for AgensGraph writes only**
   (smallest change).  Routes `upsert_knowledge_graph_async`'s sync
   inner call through its own `ThreadPoolExecutor(max_workers=1)`.
   Serializes writes (good — AgensGraph is connection-bottlenecked
   anyway) but does *not* solve GIL contention with the request loop.
   Most likely a small win, not a cure.

2. **`ProcessPoolExecutor` for the entire `BackgroundTask` body**
   (`_ingest_and_process` + `upsert_shared_memories_to_db_and_cache`).
   Removes the GIL relationship entirely.  Requires:
   * Picklable inputs (the `result` dict is already a plain dict;
     fine).
   * Worker process initializer that loads the embedding model, the
     LLM credentials, and a fresh AgensGraph connection.
   * FAISS in-process state (`vector_store.store_concepts`) needs to
     stay in the main process — only the LLM + AgensGraph pieces move.
   * Lifespan hook to start/stop the pool cleanly.
   This is a self-contained refactor inside CFN-svc, ~150 lines.

3. **Sidecar ingestion service** (largest).  Same logic moved behind
   an HTTP/queue interface in its own container.  Long-term cleaner,
   but a real architecture change.

My recommendation is **option 2**: it is the smallest change that can
actually remove the AgensGraph wedger, and it composes cleanly with
v4-A (acompletion) and v4-B-batch (batched embeddings) which are
already merged.

## Status

* Patch saved on local branch:
  * `ioc-cfn-cognition-engines` → `experiment/cfn-decide-pr-e-v4b`
* Patched container in place; v4-A + v4-B-batch active.
* CFN logs captured at `/tmp/cfn_v4b_batch.log`.
* Smoke logs at `/home/ubuntu/.mycelium/e2e-logs/pr_e_v4b_batch_smoke_20260426_232117.log`.
* Trace files:
  * `/home/ubuntu/.mycelium/e2e-logs/traces/test_40_distributed_two_agent_20260426_232435_passed.json`
  * `/home/ubuntu/.mycelium/e2e-logs/traces/test_41_distributed_three_agent_20260426_232738_passed.json`
