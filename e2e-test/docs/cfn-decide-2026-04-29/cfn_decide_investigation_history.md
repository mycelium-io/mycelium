# CFN `/decide` latency investigation — chronological history

A running narrative of how we went from "tests are flaky, CFN is slow" to a one-line fix that took CFN `/decide` from a p95 of ~22 seconds to ~20 milliseconds, and what we learned (correctly and incorrectly) along the way.

This document is a sibling to `cfn_decide_instrumentation_plan.md`, which describes the **final** instrumentation shape and PR plan. *This* document is the story of how we got there.

---

## Phase 0: starting state (before instrumentation)

**Symptom.** Mycelium's distributed e2e tests (`test_40` through `test_46`) were flaky. `test_41_distributed_three_agent` in particular would intermittently stall, time out, or fail mid-negotiation with no clear pattern. Some rounds completed in seconds; others took minutes; some never returned.

**Side concern.** Postgres connection counts on `mycelium-db` would climb across iterations, eventually hitting `max_connections` and producing `TooManyConnectionsError` cascades. This was largely mitigated mid-investigation by:

- Server-side fix `mycelium-io/mycelium#166` (release `LISTEN` connections on client disconnect)
- A new issue filed against the openclaw plugin: `mycelium-io/mycelium#175` (client-side SSE subscription leak)
- Restarting `openclaw-gateway` between test iterations

These are both real bugs, both fixed/filed, but they turned out to be **separate from the latency story** below.

**Initial hypothesis.** "CFN `/decide` is slow because the negotiation pipeline is slow — probably an LLM call, probably the Step 4 alignment validation."

This hypothesis was **wrong**, in instructive ways. The data eventually showed `pipeline.async_execute` itself runs in 1–6 ms; the time was being spent everywhere else.

---

## Phase 1: round-trace plumbing (Mycelium side)

Before we could instrument CFN, we needed Mycelium to capture and surface whatever CFN reported. We added a `_RoundTrace` dataclass to `coordination.py` that records, per coordination round:

- `cfn_decide_ms` (wall time of the `decide_negotiation` call from Mycelium's perspective)
- Decision path (`all_replied`, `aborted`, etc.)
- Per-agent first-response timings
- A `cfn_internal_timing` slot ready to hold whatever envelope CFN starts emitting

Traces are written to `~/.mycelium/e2e-logs/traces/<test>_<ts>_<outcome>.json` at the end of each test. A separate analyzer script (`mycelium-e2e-test/tests/analyze_round_traces.py`) walks the trace directory and prints per-test summaries, aggregate distributions, and a "long rounds" detail block.

This was zero-risk plumbing — fields default to `None`, so traces are valid against both instrumented and unpatched CFN.

---

## Phase 2: Site 1 — the route handler envelope (CFN)

**Hypothesis being tested.** "Is the negotiation pipeline (`pipeline.async_execute`) the slow part?"

**Patch.** In `ioc-cognition-fabric-node-svc`'s `src/app/api/semantic_nego.py`, wrap the pipeline call and the `to_dict` serialisation with `time.perf_counter()` stamps, emit a `_timing` dict on the response.

**Finding.** `pipeline_ms` was *fast* — 1–6 ms median. `to_dict_ms` was 0–1 ms. `total_route_ms` was *also* fast in the route handler itself.

So where did the seconds go? Mycelium would observe a 22-second `cfn_decide_ms`, yet CFN's own route handler said "I returned in 6 ms". That's a 22-second gap *outside* the route handler.

This was the first hypothesis-overturning data point. **The pipeline isn't slow.**

---

## Phase 3: Site 2 — `async_execute` thread breakdown (engines)

**Hypothesis being tested.** "Maybe the work inside the synchronous `execute()` (which runs via `asyncio.to_thread`) is slow, and the route-handler `pipeline_ms` is misleading because Site 1 measures the wrong thing."

**Patch.** In `ioc-cfn-cognition-engines`, decompose the `to_thread` call into three measurable phases:

- `thread_wait_ms` — time queued in the thread pool before a worker picks it up
- `in_thread_ms` — time actually executing `self.execute()`
- `post_thread_resume_ms` — time between thread completion and the awaiting coroutine resuming on the event loop

**First finding.** In early traces, all three were small. The pipeline itself was, again, fast. The gap was *still* somewhere else.

**Late finding** (Phase 7, batch data). Under sustained load, `thread_wait_ms` and `post_thread_resume_ms` would both spike to **tens of seconds** while `in_thread_ms` stayed at 1–3 ms. This was the smoking gun for what eventually became the fix — but we didn't see it until the batch run.

---

## Phase 4: Site 3 — per-request timing across FastAPI internals (CFN)

**Hypothesis being tested.** "Maybe the gap is in FastAPI's request lifecycle — middleware, dependency resolution, body parsing — *before* the route handler body executes."

**Patch.** Created `src/app/api/_request_timing.py`: a `ContextVar`-scoped per-request bucket exposing `timing_reset()`, `timing_stamp(key, value)`, and a `with timing_stage(key):` context manager. Installed an HTTP middleware in `main.py` that resets the bucket and stamps `request_started_perf` at request entry. Wrapped each significant FastAPI dependency body with `with timing_stage(...)`:

- `check_workspace_and_mas_ms` — workspace/MAS validation dependency
- `vector_cache_layer_ms` — `get_vector_cache_layer_for_mas` dependency
- `rag_cache_layer_ms` — `get_rag_cache_layer_for_mas` dependency
- `route_handler_ms` — total route handler runtime

The bucket gets folded into the `_timing` envelope right before the response is returned.

**Pitfall (worth flagging).** The first attempt wrapped the `Depends(...)` *factory* with a new function that re-called the original. This re-entered FastAPI's resolver and broke dependency injection in subtle ways. Fixed by inserting `with timing_stage(...):` *inside* the dependency body instead. (This is now documented in the plan doc as a gotcha.)

**Finding.** All Site 3 stages came back at **0–6 ms** consistently. FastAPI was not the bottleneck. The 22-second gap was *also* not in dependency resolution.

By this point we had measured: pipeline (fast), thread (fast), `to_dict` (fast), middleware (fast), dependencies (fast), route handler (fast). The only thing left was the network or the queue *outside* the FastAPI handler.

---

## Phase 5: Site 5 — wire wall-clock (Mycelium → CFN)

**Hypothesis being tested.** "Is the gap in network transport between containers, or in uvicorn's accept queue?"

**Patch.** Mycelium stamps `time.time_ns()` into a request header `X-Mycelium-Sent-Wall-Ns` immediately before `httpx`'s `client.post()` returns. CFN's middleware reads the header on first chance, computes the delta, and stamps `wire_to_middleware_ms` into the timing bucket.

Both containers share the host kernel clock (loopback networking on the same Docker host), so skew is sub-millisecond. Negative deltas get clamped at 0 to swallow VDSO jitter.

**Finding — the first real culprit.** `wire_to_middleware_ms` came back at **20,131 ms** on the slow round we captured. That's 20 seconds between Mycelium calling `client.post()` and CFN's middleware actually executing. On loopback. With a few-KB POST body.

This had to be **uvicorn's accept queue backed up**. CFN was accepting the connection but not processing it because the worker was busy. CFN runs a single uvicorn worker, so any blockage in the worker stops new requests from being processed.

But blocking on what? The route handler was fast. The pipeline was fast. The dependencies were fast. Yet *something* in the worker was holding the loop long enough to back up an accept queue by 20 seconds.

---

## Phase 6: Site 6 — loop-lag sampler with stack snapshots (CFN)

**Hypothesis being tested.** "What is actually holding CFN's event loop?"

**Patch.** Created `src/app/api/_loop_lag.py`: a background coroutine that loops on `asyncio.wait_for(stop.wait(), timeout=10ms)`. The amount by which `loop.time() - sleep_start` exceeds 10 ms is the event-loop lag — i.e. how long the loop spent unable to schedule the sampler. Recorded into a ring buffer.

When a sample exceeds `WEDGE_THRESHOLD_MS` (default 500 ms), the sampler walks `asyncio.all_tasks()`, takes a stack snapshot of each, and emits a structured warning naming the top frame of each task. Throttled to one snapshot per second to avoid log flooding.

Lifespan hook starts the sampler at app startup and stops it at shutdown. Per-request lag stats are emitted as `X-Cfn-Loop-Lag-*` response headers (since middleware can't append to a JSON response body that's already been serialised). Mycelium reads the headers and folds them into `cfn_call_timing`.

**Finding — named culprits.** Stack snapshots from wedge events consistently named:

- `litellm._service_logger.async_service_success_hook` — the LiteLLM async callback fan-out, holding the loop while running synchronous user-supplied callbacks
- `evidence/multi_entities._top_k_candidates` — the concept retrieval path, calling `concept_repo.similar_with_neighbors_async` which executes a sync Cypher `MATCH` against AgensGraph
- `evidence/rag_retrieval.retrieve_rag_top_k` — FAISS retrieval, dispatched via `to_thread`

But also, *crucially*, almost every wedge stack ended at the same line:

```
File "/usr/local/lib/python3.11/asyncio/threads.py", line 25, in to_thread
    return await loop.run_in_executor(None, func_call)
```

These weren't tasks running CPU-heavy code. These were tasks **waiting for a thread to be available**.

---

## Phase 7: the batch run that re-told the story

We ran a batch of 21 tests (3 iterations × 7 tests, `test_40` through `test_46`, with `openclaw-gateway` restarts and Postgres connection probes between iterations). The aggregate had 82 coordination rounds, 76 with full `_timing` envelopes from CFN.

The aggregate distribution was unambiguous:

| Metric | median | p75 | p95 | max | What it means |
|---|---|---|---|---|---|
| `wire_to_middleware_ms` | 6 | 48 | **27,589** | **34,380** | uvicorn accept queue wedged tens of seconds |
| `thread_wait_ms` | 0 | 0 | **75,671** | **234,010** | thread pool **completely** exhausted |
| `pipeline_ms` | 1 | 3 | **75,749** | **234,069** | tracks `thread_wait_ms` exactly |
| `post_thread_resume_ms` | 0 | 0 | 58 | **40,779** | rare but catastrophic |
| `in_thread_ms` | 1 | 2 | 3 | 77 | actual work is **fast** |
| `cfn_loop_lag_p95_ms` | 0 | 1 | **29,202** | **35,465** | confirms loop wedge |

Plus: 6 of 82 rounds (8%) hit the 300-second round budget timeout and never returned a `_timing` envelope at all. These are the worst wedges, where the call simply never completed.

The story shifted with this data. The earlier framing — "event-loop wedged by CPU-bound coroutines" — was *partially* right (the litellm callback and the AgensGraph sync calls *do* hold the loop). But the dominant signal was something simpler:

**The asyncio default thread pool is too small.** CPython's default executor caps at `min(32, cpu_count + 4)` — observed at ~12 in this image. The engines pipeline dispatches **multiple `to_thread()` calls per `/decide`** (RAG retrieval, concept retrieval, LLM ranking, multi-entity extraction, batch callback runner). A handful of concurrent requests saturate the pool. Subsequent dispatches queue for tens of seconds. The await chain blocks. Loop wedges. Accept queue backs up. Cascade.

The work itself, in any one thread, is trivially fast — 1–3 ms median.

---

## Phase 8: PR E v1 — the one-line fix

In `ioc-cognition-fabric-node-svc`'s `app_lifespan`, before any other startup work:

```python
import concurrent.futures
pool_size = int(os.getenv("CFN_DEFAULT_EXECUTOR_WORKERS", "64"))
loop = asyncio.get_running_loop()
loop.set_default_executor(
    concurrent.futures.ThreadPoolExecutor(
        max_workers=pool_size,
        thread_name_prefix="cfn-default",
    )
)
```

Fourteen lines including the comment block explaining why. Configurable via env var, defaults to 64.

Deployed via `docker cp` of the patched `main.py` into the running CFN container, plus `docker restart`.

**Smoke test (single `test_41` run, 1 round before failure):**

| Metric | Baseline (n=82) | Post-fix (n=1) |
|---|---|---|
| `cfn_decide_ms` (Mycelium-observed) | median 932, p95 21,896, max 300,020 | **21** |
| `http_ms` (Mycelium httpx) | median 25, p95 75,787, max 259,714 | **11** |
| `cfn_loop_lag_max_ms` (CFN-side, per-request) | mean 5,758, p95 30,583, max 35,465 | **0** |
| `cfn_loop_lag_p95_ms` | mean 4,583, p95 29,202 | **0** |

Three to four orders of magnitude on the p95s. The fix did exactly what the data predicted.

---

## Phase 9: a different bug, hidden by the perf wedge

The smoke test still **failed** — but on a completely different assertion: `Consensus is substantive: BROKEN — Plan: CFN response processing failed — name '_stage_stamp' is not defined`.

This is a `NameError` in Mycelium's `coordination.py`: a stale reference to `_stage_stamp` that should have been `cfn_timing_stage` (left over from an in-flight rename during the Site 4 work). The bug had been latent for days, but every prior test run hit the perf wedge first and never reached the `_normalize_cfn_decide_response` code path that triggered the `NameError`.

Now that `/decide` returns in 20 ms instead of 20 seconds, the test gets *all the way through* one round, hits the broken code path, and fails fast.

**Lesson.** Removing the dominant failure mode often reveals the next one immediately. This is normal and good. We fixed the `NameError` (one-line: add `cfn_timing_stage` to the import block in `coordination.py`) and rebuilt mycelium-backend.

---

## Phase 10: post-fix wider validation

A 3-test smoke (`test_40`, `test_41`, `test_42`) ran clean — first time we've seen all three pass in a single run. Aggregate of 33 rounds: `thread_wait_ms` p95 = 2 ms (was 75,671 ms), all 33 rounds got `_timing` envelopes back, no watchdog timeouts. One residual 58-second outlier round in `test_40` showed the new pattern cleanly: `thread_wait_ms = 37 ms` (fix working), `in_thread_ms = 419 ms` (work itself fine), but `post_thread_resume_ms = 27,746 ms` — a *pure* event-loop wedge after the thread completed. This is the residual we already named (litellm hook / AgensGraph sync), now isolated from the threadpool noise.

---

## Phase 11: full Phase 2 batch re-run

We then re-ran the original Phase 2 driver: 3 iterations × `test_40..test_46`, gateway restarts and Postgres probe between iterations. 162 rounds across 21 test runs.

### Pass/fail matrix

| | Iter 1 | Iter 2 | Iter 3 |
|---|---|---|---|
| test_40 | ✅ | ✅ | ✅ |
| test_41 | ✅ | ✅ | ✅ |
| test_42 | ✅ | ✅ | ✅ |
| test_43 | ✅ | ✅ | ✅ |
| test_44 | ✅ | ❌ | ❌ |
| test_45 | ✅ | ✅ | ✅ |
| test_46 | ❌ | ✅ | ✅ |

**18/21 passed.** No watchdog timeouts. No synthesis fallbacks. No iter-to-iter degradation. Pre-fix this matrix had cascading failures from state leakage; post-fix the failures are scattered and don't repeat across iterations on the same test.

### Threadpool fix held at scale

| Metric | Pre-fix baseline (n=82) | Post-fix batch (n=162) | Change |
|---|---|---|---|
| `thread_wait_ms` p95 | 75,671 ms | 3 ms | 25,000× ↓ |
| `thread_wait_ms` max | 234,010 ms | 74 ms | 3,000× ↓ |
| `in_thread_ms` median | 1 ms | 1 ms | flat |
| Round failure rate | ~30% (cascading) | 0% | gone |
| `cfn_status` reaches `agreed` | rare | 20/162 rounds | reaches consensus |
| Postgres conns iter→iter | climbed | 87 → 61 → 46 → 46 | trending down |

The threadpool wedge is unambiguously gone, both at small scale (33 rounds) and at the original batch scale (162 rounds). Postgres mitigations (#166 + gateway restarts) are working independently — connections trended *down* across iterations.

### What's now dominant in the residual long rounds

`decide` p95 is still 55 s, distributed across 103 long rounds. With the threadpool wedge out of the data, two correlated patterns now stand out:

**Pattern A — pure event-loop wedge inside CFN.**
`thread_wait_ms = 0`, `in_thread_ms = 1ms`, `post_thread_resume_ms ≈ 25–28 s`. Thread did its work instantly; loop was wedged ~28 s before the awaiting coroutine could resume. Site 6's stack snapshots already named the suspects: `litellm._service_logger.async_service_success_hook`, `concept_repo.similar_with_neighbors_async` (sync AgensGraph call). These are now the targets for PR E v2.

**Pattern B — request queued in uvicorn accept queue.**
`wire_to_middleware_ms = 25–52 s` with small `route_handler_ms`. Nine concurrent agents (3 distributed tests × 3 agents) pile up behind any single request hit by Pattern A. Pattern B is downstream of A — eliminating A should fade B naturally.

If B persists after v2, defense-in-depth options are CFN multi-worker uvicorn or a small in-process semaphore on `/decide` to bound concurrency.

### Validation summary

PR E v1 is **validated at scale** and ready to land as written. The instrumentation (PRs A/B/C/D in the plan doc) is what made this validation possible and should land permanently — the same pipeline will validate PR E v2 and catch any future regression.

---

## Phase 12: PR E v2 — wrap sync embedding paths

**Hypothesis being tested.** "With the threadpool fix in, the residual `post_thread_resume_ms` wedges are pure event-loop blocking. Wrapping the synchronous `fastembed`/MMR paths in the evidence engines with `asyncio.to_thread` should drop them off the loop."

**Patch.** `evidence/app/agent/multi_entities.py` and `single_entity.py`:
- `_entity_to_query_vec` becomes async; `preprocess_text` + `generate_embeddings` body runs via `asyncio.to_thread`.
- `mmr_select_indices` calls wrapped with `await asyncio.to_thread(mmr_select_indices, …)`.

(33 net lines; experiment branch `experiment/cfn-decide-pr-e-v2`.)

**Smoke (2 tests, 9 rounds).** Median `/decide` dropped from ~830 ms to **373 ms**. Wedger frame counts for the targeted call sites went from 138 to 2 in the loop-lag stack snapshots — the patch did exactly what it was designed to do.

**But** two long-tail outliers remained at 58 s and 68 s. Stack snapshots from those wedges named a *new* call site: `persist_negotiation_agreement_background` — the post-`/decide` knowledge-ingestion path running as a FastAPI `BackgroundTask`. The threadpool wedge was gone; a *different* loop-blocking pattern was now visible.

**Source:** `cfn_decide_pr_e_v2_results.md`.

---

## Phase 13: PR E v3 — offload the ingest BackgroundTask

**Hypothesis being tested.** "The two long-tail outliers are caused by `persist_negotiation_agreement_background` running synchronous LLM and embedding work directly on the event loop. Wrapping it in `asyncio.to_thread` should remove the wedge."

**Diagnosis (v3 analysis doc).** The offending sequence inside `persist_negotiation_agreement_background`:

1. `IngestDataService.ingest(...)` — calls `_build_rag_chunks` (sync embeddings) and `extract_concepts_and_relationships` which fires multiple **`litellm.completion(...)`** synchronous calls (concept extraction, relationship extraction, per-concept distillation), each a 5–30 s LLM round trip.
2. `processor.process(...)` — loops over 30+ concepts calling `embedding_manager.generate_embedding(name)` per concept, sync ONNX inference per call.
3. The downstream AgensGraph `db.save()` was *already* `to_thread`-wrapped (✅ not the wedger — important data point that paid off later in Phase 16).

**Patch (Option A).** Wrap the ingestion body and the two sync `vector_store.store_*` calls in `asyncio.to_thread`.

**Smoke result.** Median `/decide` rose from 373 ms to **590 ms**; max came down modestly from 68 s to 47 s. **Not yet a clear win.** Stack snapshots showed the wedges had migrated *into the worker thread* — `litellm.completion` was holding the GIL inside the executor thread, starving the event loop running on the main thread. Off-loading work without releasing the GIL just moves the problem.

**Sources:** `cfn_decide_pr_e_v3_analysis.md`, `cfn_decide_pr_e_v3_results.md`.

---

## Phase 14: PR E v4-A — switch to `litellm.acompletion`

**Hypothesis being tested.** "If `litellm.completion` is holding the GIL, then `litellm.acompletion` — async by design — will release it during HTTP/streaming waits and let the event loop breathe."

**Patch.** Added `_llm_extract_concepts_async`, `_llm_extract_relationships_async`, `extract_concepts_and_relationships_async` in `ingestion/app/agent/service.py` (using `litellm.acompletion`), and `IngestDataService.ingest_async`. `persist_negotiation_agreement_background` now `await`s `ingest_service.ingest_async(...)` directly. Sync API preserved.

**Smoke result.** **Regression.**

| Metric | v3 (sync LLM in `to_thread`) | v4-A (`acompletion`) |
|---|---:|---:|
| p50 `cfn_decide_ms` | 590 | **841** |
| p95 / max | 46,735 | **57,312** |
| wedges (>500 ms lag) | 11 | **25** |

Why did acompletion make things *worse*? Two reasons that took the next round of profiling to disentangle: (a) `litellm.acompletion` against Bedrock is implemented as a sync-under-await — the underlying boto/Bedrock SDK call is synchronous, so the "async" wrapper just yields once and then blocks the loop for the full LLM call duration; (b) the v4-A change *added* concurrency on the event loop (multiple awaits in flight at once) without actually making the work non-blocking, increasing GIL pressure further.

**Source:** `cfn_decide_pr_e_v4a_results.md`.

---

## Phase 15: PR E v4-B (part 1) — batch the per-concept ONNX calls

**Hypothesis being tested.** "If `acompletion` isn't actually async on Bedrock, at least the per-concept embedding loop (30+ sync `fastembed.embed()` calls in a row) is real CPU work we can collapse into one batched ONNX call."

**Patch.** New `EmbeddingManager.generate_embeddings_batch(texts)` issues a single ONNX call for the whole list. `KnowledgeProcessor.generate_embeddings_for_concepts` calls it once per `process()` invocation instead of looping per concept.

**Smoke result.** Partial relief on the tail.

| Metric | v3 | v4-A | **v4-B-batch** |
|---|---:|---:|---:|
| p50 ms | 590 | 841 | **624** |
| p95 / max ms | 46,735 | 57,312 | **30,774** |
| mean ms | 7,816 | 9,032 | **5,574** |
| wedges (>500 ms lag) | 11 | 25 | **13** |

Median is back near v3, max is down ~16 s, wedge count is down ~50% from v4-A. Not a knockout, but enough to ship as a follow-on fix. The remaining wedges still pointed at the LLM phase, not the embedding phase.

**Source:** `cfn_decide_pr_e_v4b_results.md`.

---

## Phase 16: KXP / AgensGraph profiling — ruling out the long-suspected wedger

**Hypothesis being tested.** "The remaining 25–35 s wedges are inside `upsert_knowledge_graph_async` — the AgensGraph synchronous SQLAlchemy/psycopg2 save loop. An N+1-style write pattern would explain it."

**Method.** Patched `GraphDB.save()` in `knowledge_memory`'s AgensGraph adapter to log per-phase elapsed times for every successful save: `connect+set_path_ms`, `exists_nodes_ms/_n`, `exists_edges_ms/_n`, `create_nodes_ms/_n`, `create_edges_ms/_n`, `total_ms`. Ran a smoke with the loop-lag sampler still active and correlated wedge timestamps to save phases.

**Finding.** **The N+1 SQL hypothesis was wrong.** Two real saves observed during the smoke completed in **582 ms** and **697 ms** total respectively. Meanwhile wedges of 23–37 s continued to fire during the same window. Crucially:

- **Wedges fire during ingests that never reach `db.save()`.** The wedge timestamps line up with the LLM extraction phase (the `litellm.acompletion` block from v4-A), not the graph save phase.
- **`db.save()` was already correctly `to_thread`-wrapped.** Phase 13 had noted this in passing; Phase 16 confirmed it with timing data.

So three rounds of v3/v4 chasing the LLM/embedding paths had been hunting the right bottleneck — AgensGraph batching was a planned defence-in-depth that turned out not to be needed because it was never the cause.

The recommendation flipped: **drop AgensGraph batching from the roadmap; pursue v4-C (process-isolated ingest) plus cheap mitigations** — an `asyncio.Semaphore` capping concurrent ingest tasks, and caching the `EmbeddingManager` model at module level so it isn't re-instantiated per request.

**Source:** `cfn_decide_kxp_profile_results.md`.

---

## Phase 17: outcome — what shipped, what was deferred, what we learned

**Shipped:**
- PR E v1 (executor pool bump) — landed and held at scale (Phase 11).
- PR E v2 (sync embedding `to_thread` wrap) — landed.
- PR E v4-B part 1 (batched ONNX embeddings) — landed.
- All instrumentation: round trace plumbing, Site 1–6 timing envelope, loop-lag sampler with stack snapshots, wire wall-clock header.

**Deferred:**
- PR E v4-C (move ingest into a `ProcessPoolExecutor`). Real fix for the residual GIL wedges, but non-trivial: picklability of the ingestion service, FAISS cache coherency across processes, and the Go CFN rewrite (`ioc-cfn-svc`) on the horizon all argue for waiting until the next batch of profiling justifies the cost.
- AgensGraph batching — **dropped** based on Phase 16. Ranks below the cheap mitigations.

**Recommended cheap mitigations (filed as issues):**
- `asyncio.Semaphore` capping concurrent ingest BackgroundTasks (prevents the worst pile-ups without process isolation).
- Cache the `EmbeddingManager` (and the loaded `fastembed` model) at module level instead of per-request instantiation.

These shipped as PR #38 on `cisco-eti/ioc-cognition-fabric-node-svc` (the tracing envelope alone) and follow-up issues #10, #16, #17 on `outshift-open/ioc-cognition-fabric-node-svc` for the residual mitigations.

---

## Phase 18: upstreaming and provenance

The investigation patches that lived as `docker cp` overlays on running containers were ported back to proper PRs:

- **`cisco-eti/ioc-cognition-fabric-node-svc#38`** — the tracing envelope (Sites 1, 2, 3, 5, 6: route handler timing, thread phase decomposition, `_request_timing.py`, `_loop_lag.py`, `X-Mycelium-Sent-Wall-Ns` header reader). DCO-signed; license headers added on the new files (`_loop_lag.py`, `_request_timing.py`).
- **`outshift-open/ioc-cognition-fabric-node-svc#9`** — the same patch ported to the public-facing fork. Forked through `sfph/` because direct push wasn't permitted on `outshift-open`. DCO-signed and license-headed.
- **`outshift-open/ioc-cognition-fabric-node-svc` issues #10, #16, #17** — the deferred residual mitigations (ingest semaphore, cached embedding model, scoped process pool).

**Architectural note discovered during upstreaming:** `cisco-eti/ioc-cfn-svc` (Go) is a planned replacement for `ioc-cognition-fabric-node-svc` (Python). The Go rewrite externalizes cognition-engines and knowledge-memory as HTTP services, which both relaxes some of these wedge patterns (separate processes for the ingest pipeline) and renders the v4-C process-pool work redundant in the long run. This is part of why v4-C was deferred rather than rushed.

The analyzer extensions (`tests/analyze_round_traces.py` `--wedges`, `--compare-dir`, `cfn_internal_timing` aggregation) live on `sfph/mycelium-e2e-test` branch `feat/cfn-decide-timing-scripts` — the same machinery that ran ad-hoc against smoke logs in phases 12–16, now committed so the same per-fix attribution is reproducible from any future trace dir without one-off scripts.

---

## What we learned, by category

### About the system

1. **CFN runs a single uvicorn worker** with the default asyncio thread pool. Every `to_thread` in the engines pipeline competes for ~12 worker threads. Under any concurrency at all, this saturates.
2. **The "event loop wedged by CPU" framing was a third-right.** Three distinct mechanisms produce loop wedges in CFN, and the investigation surfaced them in this order:
   - **Threadpool starvation** (Phase 7) — the *dominant* signal at scale; fixed by PR E v1.
   - **Sync code on the event loop** (Phases 12–13) — `fastembed`/MMR and the ingestion BackgroundTask running their LLM calls on the loop directly; fixed by PR E v2 and PR E v3.
   - **GIL contention from `to_thread`-wrapped sync code** (Phases 14–16) — the residual pattern. Wrapping a CPU/GIL-bound sync call in `to_thread` moves it off the loop but *doesn't* free the loop if the worker thread holds the GIL throughout. `litellm.acompletion` against Bedrock is the painful counter-example: the wrapper is async-shaped but the underlying call is sync-under-await. The cure for this layer is process isolation (deferred v4-C) or eliminating the sync work (caching, batching).
   The instinct "just add more `to_thread`" is right at layer 1, neutral at layer 2, and *actively harmful* at layer 3.
3. **A 20-second `wire_to_middleware_ms` is the unmistakable fingerprint of accept-queue backup.** Network is not 20 seconds slow on loopback. If the middleware stamp says 20s, the worker was busy for 20s.
4. **`thread_wait_ms ≈ pipeline_ms` and `in_thread_ms` ≈ 1ms** is the unmistakable fingerprint of thread pool saturation. The work isn't slow; the queue is.
5. **`thread_wait_ms ≈ 0`, `in_thread_ms ≈ 1ms`, `post_thread_resume_ms` huge** is the fingerprint of pattern (2c) above — work completed instantly, but the loop was wedged by something else (often a *concurrent* GIL-bound `to_thread` worker) before the awaiting coroutine could resume.
6. **AgensGraph was a red herring.** Three months of "the AgensGraph save loop is slow" intuition turned out to be wrong once measured (Phase 16). `db.save()` runs in 600–700 ms; the wedges fire elsewhere. **Always instrument the suspect before refactoring it.**

### About the methodology

1. **Outside-in instrumentation wins.** We started at the route handler (Site 1) and worked outward — `to_thread` (Site 2), middleware/deps (Site 3), wire (Site 5), loop sampler (Site 6). Every layer either ruled itself out or pointed to the next. We never had to read CFN's source code to find the bug; the data led us there.
2. **Aggregate distributions matter more than single traces.** Single `test_41` traces showed `post_thread_resume_ms` wedges as the headline. The aggregate of 82 rounds re-ranked everything: `thread_wait_ms` was 5× larger. The original story would have led to the wrong fix.
3. **A bug that "happens sometimes" usually isn't the actual bug.** It's a downstream effect of something more systematic. The perf wedge made the consensus-assertion `NameError` look like flakiness for days.
4. **Patching a running container with `docker cp` + `docker restart` is fine for experimentation,** but it makes provenance opaque. Once the fix shape stabilises, it needs to land as proper PRs (see `cfn_decide_instrumentation_plan.md`).

### About hypothesis discipline

1. The first hypothesis ("the pipeline is slow") was wrong but useful — Site 1 ruled it out in one PR's worth of code.
2. The second hypothesis ("FastAPI dep resolution is slow") was wrong — Site 3 ruled it out.
3. The third hypothesis ("event loop is wedged by CPU-heavy work") was *partly* right — Site 6 found the wedgers, but the aggregate data showed CPU blocking was the lesser cause.
4. The fourth hypothesis ("thread pool is saturated") was right — Site 2's `thread_wait_ms` field, looked at across the aggregate, named the bug.

Each wrong hypothesis was discharged by a small, additive instrumentation patch. None of the patches needed to be reverted; they all stayed in as permanent observability. This is the right shape for this kind of investigation.

---

## Open questions and follow-ups

**Resolved during phases 12–18:**

- ~~Where is the next bottleneck?~~ → Answered. Not AgensGraph (Phase 16). The dominant residual is GIL contention in the ingest `BackgroundTask`, specifically the `litellm.acompletion`-against-Bedrock sync-under-await pattern (Phase 14) plus per-request `EmbeddingManager` instantiation. Cheap mitigations filed as `outshift-open/ioc-cognition-fabric-node-svc#16`/`#17`; full fix is process isolation, deferred as v4-C.
- ~~Are the AgensGraph wedgers worth their own fix?~~ → Answered: **no**. Phase 16 measurements showed `db.save()` runs in 600–700 ms and never coincided with wedge timestamps. AgensGraph batching dropped from the roadmap.

**Still open:**

- **Should CFN run multiple uvicorn workers?** Still open. Trade-off has sharpened: the in-process FAISS/concept caches mean adding workers ≠ free scaling, and the Go CFN rewrite (`ioc-cfn-svc`) externalizes those caches into separate HTTP services anyway. Recommendation: skip the workers conversation on the Python service; let the Go rewrite carry it.
- **Is 64 the right thread pool size?** Held up across all of phases 11–18 with no observed re-saturation. `CFN_DEFAULT_EXECUTOR_WORKERS` env var keeps this tunable without a redeploy.
- **PR E v4-C (process isolation for the ingest BackgroundTask).** Filed as `outshift-open/ioc-cognition-fabric-node-svc#10`. Real fix for the residual GIL wedges, but blocked on (a) picklability of the ingestion service objects, (b) FAISS cache coherency across processes, and (c) the Go CFN rewrite landing first. Cheap mitigations (#16, #17) buy headroom in the meantime.
- **Issue #172** (silent counter-offer drop) and **issue #175** (openclaw-gateway SSE leak) are both real and both filed; neither is on the latency critical path.

---

## File and PR pointers

### Investigation docs (this directory)

- `cfn_decide_instrumentation_plan.md` — final instrumentation shape (Sites 1–6) and PR plan
- `cfn_decide_findings_report.md` — top-level findings summary
- `cfn_decide_tracing_payoff.md` — what the timing envelope bought us
- `cfn_decide_pr_e_v2_results.md` — Phase 12 source
- `cfn_decide_pr_e_v3_analysis.md`, `cfn_decide_pr_e_v3_results.md` — Phase 13 source
- `cfn_decide_pr_e_v4a_results.md` — Phase 14 source (the regression)
- `cfn_decide_pr_e_v4b_results.md` — Phase 15 source
- `cfn_decide_kxp_profile_results.md` — Phase 16 source (AgensGraph red-herring kill)

### Upstream PRs (Phase 18)

- **`cisco-eti/ioc-cognition-fabric-node-svc#38`** — tracing envelope (Sites 1–6); merged
- **`outshift-open/ioc-cognition-fabric-node-svc#9`** — port to public fork (via `sfph/ioc-cognition-fabric-node-svc`); DCO-signed, license-headed
- **`outshift-open/ioc-cognition-fabric-node-svc` issues #10, #16, #17** — deferred residual mitigations

### Mycelium-side artifacts

- **Branch holding observation patches:** `experiment/cfn-decide-timing-envelope` off `feat/cfn-round-trace-instrumentation`
- **Round trace dir (live):** `~/.mycelium/e2e-logs/traces/`
- **Analyzer:** `sfph/mycelium-e2e-test`, branch `feat/cfn-decide-timing-scripts`, `tests/analyze_round_traces.py`
  - Now includes `--wedges` (Pattern A/B/C/D attribution), `--compare-dir` (pre/post diff), and `cfn_internal_timing` aggregation. The same per-fix slicing that was done ad-hoc during phases 12–16, promoted to a committed tool.
- **Deploy / batch scripts:** `sfph/mycelium-e2e-test/scripts/apply-cfn-decide-timing.sh`, `run-decide-timing-batch.sh`

### Snapshot evidence

- **Pre-fix batch summary:** `/tmp/analysis/batch-summary.txt` (21 traces, 82 rounds)
- **Post-fix smoke logs:** `/tmp/post-fix/smoke.log` (33 rounds, all pass)
- **Post-fix Phase 2 batch:** `~/.mycelium/e2e-logs/batch-20260426_011145/` (21 runs, 162 rounds, 18/21 pass)

### Reproducing the per-phase tables from raw traces

```bash
cd ~/mycelium-e2e-test
python tests/analyze_round_traces.py \
    --dir ~/.mycelium/e2e-logs/traces \
    --glob 'test_4*post_v4b*.json' \
    --wedges
# or compare two windows:
python tests/analyze_round_traces.py \
    --dir ~/.mycelium/e2e-logs/post_fix \
    --compare-dir ~/.mycelium/e2e-logs/pre_fix
```
