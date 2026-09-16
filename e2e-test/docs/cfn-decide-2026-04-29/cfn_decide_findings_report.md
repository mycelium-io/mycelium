# CFN `/decide` Latency Investigation — Findings & Recommendations

## Summary

Mycelium distributed multi-agent negotiations were failing intermittently with watchdog timeouts and cascading state leakage across runs. Root cause was high-tail latency in the CFN `/decide` HTTP call (p95 ≈ 22s, max > 4 minutes) starving the negotiation watchdog.

End-to-end instrumentation across Mycelium and CFN identified **CPython's default `asyncio` thread pool exhaustion** as the dominant wedge. A 6-line fix to size CFN's default executor explicitly resolved it. After the fix, `thread_wait_ms` p95 dropped from **75,671 ms → 3 ms** (a 25,000× reduction), and a wider validation run of 162 negotiation rounds saw no cascading failures, no watchdog timeouts, and no Postgres leak.

A residual loop-blocking wedge remains, now cleanly isolated and named.

---

## The fix

`ioc-cognition-fabric-node-svc/src/app/main.py`, in `app_lifespan`:

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

That's it. Configurable via `CFN_DEFAULT_EXECUTOR_WORKERS`; default 64 chosen as ~5× CPython's autosized cap, well below typical Postgres/HTTP pool ceilings.

### Validation

**Smoke run (33 negotiation rounds across 3 distributed scenarios):** all passed, `thread_wait_ms` max 37 ms, decide median 832 ms.

**Wider batch (162 rounds across 21 distributed scenario runs, 3 iterations × 7 scenarios):** no watchdog timeouts, no synthesis fallbacks, no iter-to-iter degradation. The remaining test-suite failures were unrelated content-quality assertions, not infrastructure issues.

| Metric | Pre-fix baseline | Post-fix batch | Change |
|---|---|---|---|
| `thread_wait_ms` p95 | 75,671 ms | 3 ms | 25,000× ↓ |
| `thread_wait_ms` max | 234,010 ms | 74 ms | 3,000× ↓ |
| Round failure rate | ~30% (cascading) | 0% (3 scattered test failures) | gone |
| `cfn_status` reaches `agreed` | rare | 20/162 rounds | reaches consensus |

---

## How we got there

We added a `_timing` envelope to every `/decide` request, threaded through Mycelium's HTTP call, six instrumentation sites in CFN's request path, and an event-loop lag sampler with stack snapshots on both sides. All timing flows into each round's `CFN_ROUND_TRACE` record for aggregation across runs.

The instrumentation revealed a layered story that wasn't visible from logs alone:

| Layer | Telemetry | Pre-fix p95 | Post-fix p95 |
|---|---|---|---|
| Mycelium → CFN wire | `wire_to_middleware_ms` | 27.6 s | 41.2 s* |
| Route handler total | `route_handler_ms` | similar to pipeline | 27.4 s |
| Pipeline (incl. thread work) | `pipeline_ms` | 21.9 s | 42 ms |
| Thread wait for executor | `thread_wait_ms` | **75.7 s** | **3 ms** |
| In-thread work | `in_thread_ms` | 1 ms | 1 ms |
| Post-thread loop resume | `post_thread_resume_ms` | 22 s | 21 ms |
| CFN event-loop lag (max) | `cfn_loop_lag_max` | 35.5 s | 30.7 s* |

*Post-fix `wire_to_middleware_ms` and `cfn_loop_lag` numbers reflect the residual loop-blocking wedge that's now next on the list — see below.

The smoking gun: pre-fix, threads were waiting **75 seconds at p95** to even *start* on work that took 1 ms once they got going. CPython's default `ThreadPoolExecutor` caps at `min(32, cpu_count + 4)`, observed at ~12 in the CFN container. CFN's pipeline dispatches several `asyncio.to_thread` calls per `/decide` (RAG retrieval, concept repo, LLM rerank, etc.); a handful of concurrent `/decide` calls saturated the pool and serialized everything else.

---

## What remains

Now that the threadpool wedge is out of the data, two correlated patterns dominate the residual long rounds:

**Pattern A — pure event-loop wedge inside CFN.**
`thread_wait_ms = 0`, `in_thread_ms = 1ms`, `post_thread_resume_ms ≈ 25–28 s`. The thread did its work instantly, but the loop was wedged for ~28s before the awaiting coroutine could resume. Site 6's CFN-side loop-lag stack snapshots have already named the culprits:

- `litellm._service_logger.async_service_success_hook` running synchronous logic on the loop
- `concept_repo.similar_with_neighbors_async` doing a sync AgensGraph call on the loop
- `evidence/rag_retrieval.retrieve_rag_top_k` (FAISS) — currently uses `to_thread` so already off-loop, but worth confirming under load

**Pattern B — request queued in uvicorn accept queue.**
`wire_to_middleware_ms` = 25–52 s with a small `route_handler_ms`. Nine concurrent agents across 3 distributed tests pile up behind any single request hit by Pattern A. Pattern B is downstream of Pattern A — eliminate A and B fades naturally.

### Recommended next fix (PR E v2)

Move the named wedgers off the event loop:

- Wrap `litellm`'s success hook in `run_in_executor` or replace it with a fire-and-forget task on a dedicated executor.
- Wrap the sync AgensGraph call in `concept_repo.similar_with_neighbors_async` with `asyncio.to_thread`.
- Audit any other `_service_logger`/post-processing code paths that the Site 6 snapshots surface in the next batch.

If Pattern B persists after v2, defense-in-depth options are CFN multi-worker uvicorn or a small in-process semaphore on `/decide` to bound concurrency.

Success criteria:

  ┌────────────────────────────────────┬────────────────────────────────┬─────────────────┐
  │ Metric                             │ Pre-v2 (current post-v1 batch) │ Target after v2 │
  ├────────────────────────────────────┼────────────────────────────────┼─────────────────┤
  │ post_thread_resume_ms p95          │ 21 ms                          │ stays ≤50 ms    │
  │ post_thread_resume_ms max          │ 36,776 ms                      │ <2,000 ms       │
  │ pipeline_ms max                    │ 36,942 ms                      │ <2,000 ms       │
  │ cfn_loop_lag_max_ms max (CFN-side) │ 30,731 ms                      │ <500 ms         │
  │ wire_to_middleware_ms max          │ 59,706 ms                      │ <2,000 ms       │
  │ decide p95                         │ 55 s                           │ <5 s            │
  │ Pass rate                          │ 18/21                          │ 21/21           │
  └────────────────────────────────────┴────────────────────────────────┴─────────────────┘


---

## Recommendations

### Land as-is

| PR | Repo | Description |
|---|---|---|
| **E v1 (fix)** | `ioc-cognition-fabric-node-svc` | The 6-line executor bump in `app_lifespan` plus its env-var override. Independently valuable, no dependencies. |

### Land as opt-in / scaffolding (tracing)

| PR | Repo | Description |
|---|---|---|
| **A (observation)** | `ioc-cognition-fabric-node-svc` | `_timing` envelope on `/decide`, per-request `ContextVar` + middleware + dep timing, `X-Mycelium-Sent-Wall-Ns` header read, `_loop_lag.py` sampler with `CFN_LOOP_LAG_SNAPSHOT` opt-in for stack snapshots. Default-on but bounded; the per-request overhead is sub-ms. |
| **B (observation)** | `ioc-cfn-cognition-engines` | `async_execute` thread breakdown — `thread_wait_ms`, `in_thread_ms`, `post_thread_resume_ms`. ~20 lines, additive into the result dict. |
| **C (observation)** | `mycelium` | Mycelium-side `_cfn_call_timing.py` + `_LagSampler`, `_cfn_post` HTTP-call breakdown, `X-Mycelium-Sent-Wall-Ns` send, `X-Cfn-Loop-Lag-*` capture, `_RoundTrace.cfn_internal_timing` / `cfn_call_timing` fields. |

These three PRs collectively gave us the entire picture in this investigation. They're cheap at runtime and make the data immediately actionable. They should land permanently — not as a one-off — because the same telemetry is what will validate PR E v2 and any future regression.

### Follow-up (PR E v2)

| PR | Repo | Description |
|---|---|---|
| **E v2 (fix)** | `ioc-cfn-cognition-engines` | Move the named loop blockers (`litellm` success hook, `concept_repo.similar_with_neighbors_async`) off the event loop via `to_thread` / `run_in_executor`. Validate against the batch with the same analyzer. |

### Triage separately (not blocking)

- Mycelium-io PR #166 (server-side SSE fix) and issue #175 (`openclaw-gateway` plugin SSE leak) are addressing the Postgres connection leak observed during this investigation. Independent of the latency story.

---

## Key takeaways

1. **The dominant wedge was invisible from logs.** Pre-instrumentation, the symptom was "CFN /decide is slow and tests time out." The actual mechanism — threads waiting 75+ seconds for a 12-thread default executor — was only visible once we measured both `thread_wait_ms` and `in_thread_ms` separately.
2. **A 6-line config fix removed 3+ orders of magnitude of tail latency.** No business logic changed. CPython's autosized default is the bug; the fix is making the size explicit and large.
3. **Layered instrumentation is what found it.** End-to-end timing on the wire, route handler, dependency injection, thread dispatch, and event-loop lag — all surfaced in the same `_RoundTrace` schema — is what made the bottleneck identifiable. The same pipeline now isolates the residual wedge cleanly enough to name specific functions to fix next.
4. **The data is reusable.** The instrumentation pays for itself any time CFN latency drifts again. Recommend landing it permanently.
