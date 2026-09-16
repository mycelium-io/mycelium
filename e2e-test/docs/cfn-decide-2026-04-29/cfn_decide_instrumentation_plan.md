# CFN `/decide` instrumentation plan

## TL;DR — what the data says

The `/decide` tail latency is **not in the negotiation pipeline**. `pipeline.async_execute` runs in 1–30 ms, the thread pool has zero queue wait, and `to_dict` is free. The wedge is the **CFN event loop being held by other coroutines** outside the request being measured:

- `evidence/multi_entities._top_k_candidates` (concept retrieval / `concept_repo.similar_with_neighbors_async`)
- `evidence/rag_retrieval.retrieve_rag_top_k` (FAISS via `to_thread`)
- `litellm._service_logger.async_service_success_hook` (LiteLLM callback)
- One or more `concept_repo` Cypher `MATCH` queries against AgensGraph

A single CFN uvicorn worker shares one event loop across all in-flight `/decide`, `/start`, and the background-task chain. Whichever request loses the race for the loop pays the wait — both before middleware fires *and* after `to_thread` returns.

Symptoms on a slow round captured live:

```
Mycelium http_ms              50,656 ms   ← total wait observed by client
  ├─ wire_to_middleware_ms    20,131 ms   ← request stuck in uvicorn accept queue
  └─ CFN route_handler_ms     30,051 ms   ← AND then stuck inside the handler
       ├─ pipeline_ms         30,023 ms
       │    ├─ in_thread_ms       30 ms   ← actual sync work was fast
       │    └─ post_thread_resume_ms  29,992 ms   ← couldn't get back on the loop
       └─ to_dict_ms              0 ms

CFN per-request loop-lag window: max=25,092 ms  mean=12,546 ms
```

---

## Terminology: "Sites"

A **Site** is a single, named place in the source tree where we add a small block of timing instrumentation. Each Site produces one or more named latency measurements that get bubbled up into a `_timing` envelope on the `/decide` response (or, where that's not possible, response headers), so Mycelium can capture them automatically without log-scraping. Sites are numbered roughly outside-in along the request path:

```
Site 1 = CFN route handler envelope
Site 2 = CFN async_execute thread breakdown   (incl. post_thread_resume_ms)
Site 3 = CFN FastAPI middleware + dep ContextVar timing
Site 4 = Mycelium HTTP-call breakdown + Mycelium loop-lag sampler
Site 5 = Wire wall-clock (Mycelium → CFN header → middleware)
Site 6 = CFN loop-lag sampler with stack snapshot on wedge
```

Each Site is described below, with the patch shape, the fields it produces, and the question it answers.

---

## Sites

### Site 1 — CFN route handler `_timing` envelope

**Repo:** `cisco-eti/ioc-cognition-fabric-node-svc`
**File:** `src/app/api/semantic_nego.py`

Wraps `pipeline.async_execute` and `to_dict` and emits a `_timing` envelope on the response body.

```python
t0 = time.perf_counter()
result = await pipeline.async_execute(...)
t_pipeline_done = time.perf_counter()
converted = to_dict(result)
t_serialised = time.perf_counter()

if isinstance(result, dict):
    timing = result.setdefault("_timing", {})
    timing["pipeline_ms"]     = round((t_pipeline_done - t0)              * 1000, 2)
    timing["to_dict_ms"]      = round((t_serialised    - t_pipeline_done) * 1000, 2)
    timing["total_route_ms"]  = round((time.perf_counter() - t0)          * 1000, 2)
return result
```

**Fields produced:** `pipeline_ms`, `to_dict_ms`, `total_route_ms`, `pipeline_plus_persist_setup_ms`.

**Answers:** Is `/decide` slow because of pipeline work, response serialisation, or background-task dispatch?

---

### Site 2 — CFN `async_execute` thread breakdown

**Repo:** `cisco-eti/ioc-cfn-cognition-engines`
**File:** `semantic_negotiation/app/agent/semantic_negotiation.py`

Distinguishes thread-pool wait, in-thread work, and the post-thread resume gap.

```python
async def async_execute(self, ...):
    queued_at = time.perf_counter()
    timing = {}
    def _run_sync(*a, **kw):
        timing["entered_at"] = time.perf_counter()
        try:
            return self.execute(*a, **kw)
        finally:
            timing["exited_at"] = time.perf_counter()
    result = await asyncio.to_thread(_run_sync, ...)
    resumed_at = time.perf_counter()
    if isinstance(result, dict):
        env = result.setdefault("_timing", {})
        env["thread_wait_ms"]         = round((timing["entered_at"] - queued_at)        * 1000, 2)
        env["in_thread_ms"]           = round((timing["exited_at"]  - timing["entered_at"]) * 1000, 2)
        env["post_thread_resume_ms"]  = round((resumed_at - timing["exited_at"])        * 1000, 2)
    return result
```

**Fields produced:** `thread_wait_ms`, `in_thread_ms`, `post_thread_resume_ms`.

**Answers:** Is the work itself slow (`in_thread_ms`), or is the loop too busy to dispatch the thread (`thread_wait_ms`) or to wake the awaiting coroutine after the thread finishes (`post_thread_resume_ms`)?

---

### Site 3 — CFN per-request middleware + dependency timing

**Repo:** `cisco-eti/ioc-cognition-fabric-node-svc`
**Files:**
- `src/app/api/_request_timing.py` (new) — `ContextVar`-scoped per-request bucket with `timing_reset()`, `timing_stamp(key, val)`, and a `with timing_stage(key):` helper.
- `src/app/main.py` — middleware installs a fresh bucket and stamps `request_started_perf`.
- `src/app/api/shared_memory.py`, `src/app/utils/mgmt_plane_client.py` — wrap each FastAPI dependency body with `with timing_stage("..."):` to capture pre-handler work.

```python
# middleware
@app.middleware("http")
async def _stamp_request_start(request, call_next):
    bucket = timing_reset()
    timing_stamp("request_started_perf", time.perf_counter())
    response = await call_next(request)
    bucket["request_finished_perf"] = time.perf_counter()
    return response

# in a Depends factory
def get_vector_cache_layer_for_mas(...):
    with timing_stage("vector_cache_layer_ms"):
        ...do work...
```

**Fields produced:** `route_handler_ms`, `check_workspace_and_mas_ms`, `vector_cache_layer_ms`, `rag_cache_layer_ms`, plus any per-dep stages added later. Bubbled into `_timing` by Site 1's handler before it returns.

**Answers:** Once the middleware fires, where does the request spend its time before reaching the handler body? Useful for any CFN endpoint, not just `/decide`.

**Gotcha:** Don't decorate dependency factories with a wrapper function — that re-enters FastAPI's resolver and breaks the dep graph. Insert `with timing_stage(...):` *inside* the dep body.

---

### Site 4 — Mycelium HTTP-call breakdown + loop-lag sampler

**Repo:** `mycelium-io/mycelium`
**Files:**
- `fastapi-backend/app/services/_cfn_call_timing.py` (new) — mirror of CFN's Site 3 module: a `ContextVar` bucket and `cfn_timing_stage`/`cfn_timing_stamp` helpers, plus a small background `_LagSampler` that samples Mycelium's own event-loop lag during the call.
- `fastapi-backend/app/services/cfn_negotiation.py` — `_cfn_post` decomposes the `httpx.AsyncClient` call into stages.
- `fastapi-backend/app/services/coordination.py` — wraps each `decide_negotiation` call with a fresh timing bucket and lag sampler, captures the snapshot into `_RoundTrace.cfn_call_timing`.

```python
client_cm = httpx.AsyncClient(timeout=...)
with cfn_timing_stage("client_setup_ms"):
    client = await client_cm.__aenter__()
entered = True
try:
    with cfn_timing_stage("http_ms"):
        resp = await client.post(url, json=body, headers={...})
    with cfn_timing_stage("raise_for_status_ms"):
        resp.raise_for_status()
    with cfn_timing_stage("json_parse_ms"):
        data = resp.json()
    cfn_timing_stamp("response_bytes", len(resp.content))
    return data
finally:
    if entered:
        with cfn_timing_stage("client_close_ms"):
            await client_cm.__aexit__(None, None, None)
```

**Fields produced:** `client_setup_ms`, `http_ms`, `raise_for_status_ms`, `json_parse_ms`, `client_close_ms`, `response_bytes`, plus `loop_lag_samples_n`, `loop_lag_mean_ms`, `loop_lag_p95_ms`, `loop_lag_max_ms` from the sampler.

**Answers:** Is the gap on Mycelium's side of the call? (Is Mycelium's own event loop blocked? Is `httpx` slow to set up the client? Does response parsing dominate?)

**Gotcha:** Manual `__aenter__/__aexit__` requires the `entered` flag — calling `__aexit__` on a half-initialised client raises and masks the original error.

---

### Site 5 — Wire wall-clock delta

**Repos:** Both, paired.

**Mycelium** sends a wall-clock timestamp in a request header just before `client.post`:

```python
import time as _time
sent_ns = _time.time_ns()
cfn_timing_stamp("sent_wall_ns", sent_ns)
headers = {"X-Mycelium-Sent-Wall-Ns": str(sent_ns)}
resp = await client.post(url, json=body, headers=headers)
```

**CFN** middleware reads it and stamps the delta:

```python
sent_ns_hdr = request.headers.get("x-mycelium-sent-wall-ns")
if sent_ns_hdr:
    try:
        wire_ms = (time.time_ns() - int(sent_ns_hdr)) / 1_000_000.0
        timing_stamp("wire_to_middleware_ms", round(max(0.0, wire_ms), 2))
    except (ValueError, TypeError):
        pass
```

**Field produced:** `wire_to_middleware_ms`.

**Answers:** How much of the gap is "between Mycelium's `await client.post(...)` and CFN's middleware actually firing"? On a single host this is dominated by uvicorn's accept queue.

**Gotcha:** Containers on the same host share the kernel clock, so skew is sub-millisecond. Don't try to do NTP correction; clamp negative deltas at 0 to swallow VDSO jitter.

---

### Site 6 — CFN loop-lag sampler with stack snapshot

**Repo:** `cisco-eti/ioc-cognition-fabric-node-svc`
**Files:**
- `src/app/api/_loop_lag.py` (new) — a background coroutine that sleeps in 10 ms ticks, records `(loop.time() − sleep_start − interval)` as event-loop block time, and on any sample exceeding `WEDGE_THRESHOLD_MS` (default 500 ms) snapshots `asyncio.all_tasks()` with each task's current stack frame and emits a structured warning.
- `src/app/main.py` — starts the sampler in the lifespan context, exposes a per-request window via `loop_lag_window_start()` / `loop_lag_window_stop()`, and emits the per-request summary as `X-Cfn-Loop-Lag-*` response headers.
- `fastapi-backend/app/services/cfn_negotiation.py` — Mycelium reads the headers and stamps them into `cfn_call_timing` as `cfn_loop_lag_*_ms`.

```python
@dataclass
class _SamplerState:
    task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    samples: list[tuple[float, float]] = field(default_factory=list)
    last_snapshot_at: float = 0.0

async def _run_sampler():
    loop = asyncio.get_running_loop()
    while not _state.stop_event.is_set():
        t0 = loop.time()
        try:
            await asyncio.wait_for(_state.stop_event.wait(), timeout=SAMPLE_INTERVAL_S)
            return
        except asyncio.TimeoutError:
            pass
        lag_ms = max(0.0, (loop.time() - t0 - SAMPLE_INTERVAL_S) * 1000.0)
        _state.samples.append((loop.time(), lag_ms))
        if lag_ms >= WEDGE_THRESHOLD_MS and (loop.time() - _state.last_snapshot_at) >= 1.0:
            _state.last_snapshot_at = loop.time()
            for t in asyncio.all_tasks():
                if t is asyncio.current_task():
                    continue
                stack = t.get_stack(limit=8)
                logger.warning("  task %s top=%s", t.get_name(), _fmt_top(stack))
```

**Fields produced (per-request, via response headers):** `cfn_loop_lag_samples_n`, `cfn_loop_lag_mean_ms`, `cfn_loop_lag_p95_ms`, `cfn_loop_lag_max_ms`. Plus structured warnings in CFN logs naming the wedger.

**Answers:** When the loop is wedged, which coroutine is holding it? The summary tells you "during this request, the loop was stalled X ms"; the log warnings tell you "by these tasks."

**Gotchas:**
- The middleware can't append to a JSON response body (the route handler has already serialised it before middleware's `call_next` returns). Per-request lag stats are emitted as response **headers** instead and Mycelium captures them on the way back.
- Stack snapshots taken from a sleeping coroutine sampler will miss pure-CPU wedgers — the sampler is `await asyncio.sleep`-ing while the CPU block runs, then wakes up to find an idle loop. To catch CPU wedgers you'd need a separate signal-driven sampler (not a coroutine). The await-blocked wedgers — which is what we have — are caught reliably.

---

## Mycelium-side capture

`fastapi-backend/app/services/coordination.py`'s `_RoundTrace` carries:

```python
cfn_internal_timing: dict | None = None   # Sites 1, 2, 3, 5, 6 (CFN's own _timing)
cfn_call_timing:     dict | None = None   # Site 4 + Site 6 headers (Mycelium-side breakdown)
```

Both are surfaced by `mycelium-e2e-test/tests/analyze_round_traces.py` as their own breakdown tables, and the long-rounds detail block prints CFN's `_timing` envelope inline so you don't have to grep traces.

---

## Suggested PR sequencing

One PR per repo for the instrumentation, plus one separate PR for the fix. The split between **observation** and **fix** in `ioc-cfn-cognition-engines` is deliberate: observation is a zero-risk additive change, the fix is a real correctness change that warrants its own review.

| PR | Target repo                                        | Sites         | Type        | Depends on            | Scope                                                                                                                                                                                                                                                |
| -- | -------------------------------------------------- | ------------- | ----------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A  | `cisco-eti/ioc-cognition-fabric-node-svc`          | 1, 3, 5, 6    | observation | —                     | All CFN service-side instrumentation in one cohesive change: `_timing` envelope on `/decide`, per-request `ContextVar` + middleware + dep timing, `X-Mycelium-Sent-Wall-Ns` header read, `_loop_lag.py` sampler + lifespan + per-request headers.    |
| B  | `cisco-eti/ioc-cfn-cognition-engines`              | 2             | observation | —                     | `async_execute` thread breakdown — `thread_wait_ms`, `in_thread_ms`, `post_thread_resume_ms`. ~20 lines, additive into the result dict (PR A bubbles them into `_timing`).                                                                          |
| C  | `mycelium-io/mycelium`                             | 4 + send/recv | observation | none (tolerant)       | Mycelium-side story end-to-end: `_cfn_call_timing.py` + `_LagSampler`, `_cfn_post` HTTP-call breakdown, `X-Mycelium-Sent-Wall-Ns` header send, `X-Cfn-Loop-Lag-*` header capture, `_RoundTrace.cfn_internal_timing` / `cfn_call_timing` fields.       |
| D  | `sfph/mycelium-e2e-test`                           | —             | tooling     | C                     | `analyze_round_traces.py` surfaces both new envelopes plus the long-rounds detail block.                                                                                                                                                            |
| E  | `cisco-eti/ioc-cfn-cognition-engines`              | n/a           | **fix**     | B (narrative only)    | Move the wedgers named by Site 6 — `evidence._top_k_candidates`, `concept_repo.similar_with_neighbors_async`, `litellm` async success hook — off the event loop. `to_thread` for sync paths or `run_in_executor` with a dedicated executor.          |

Dependency notes:

- **A, B, C are fully independent** and can land in parallel. Each ships value standalone.
- **C is the right one to land first** if you want to start collecting data immediately — it's tolerant of missing fields, so it captures whatever CFN happens to emit (today: nothing; after A+B: full envelope).
- **D depends on C** because it's a pure consumer of the trace shape C emits.
- **B → E is narrative, not code.** B patches `async_execute` (measurement); E patches the actual wedgers (`evidence/multi_entities.py`, `concept_repo`, the LiteLLM callback). Different files, no shared symbols. The data justifying E comes from the experiment branch + analyzer, not from B being merged to main.
- A, B, C, D are pure observation: zero behaviour change, zero new runtime deps, all fields are additive on the response or in new headers. They can ship without coordination across repos.

### Should B and E be combined?

Both target `ioc-cfn-cognition-engines`. The trade-off is real either way:

**Combine (one PR against engines)**
- One trip through the engines team's review queue.
- Tells a complete "here's the measurement, here's the fix" story in one diff.
- B is small enough (~20 lines) that it doesn't materially expand the change.

**Keep separate (recommended default)**
- Different risk profiles. B is mechanically obvious; E will spawn real questions ("what executor size? ordering guarantees? was `_top_k_candidates` relying on being on the loop?"). Bundling means B can't merge until those are resolved.
- Easier to revert E alone if the fix introduces a regression, without losing the observation infrastructure that helps diagnose what went wrong.
- Lets B land on the team's slow days while E waits for the right reviewer.

**Heuristic:** if the engines team is small/fast and prefers fewer PRs, combine. If reviews there typically take days and the fix is likely to provoke debate, split — and don't let B get held hostage to that debate.

---

## Implementation gotchas worth remembering

These are worth flagging if anyone repeats this exercise on another service.

1. **FastAPI dependency wrapping recurses.** Wrapping a `Depends(...)` factory with a new function that calls the original re-enters FastAPI's resolver. Insert `with timing_stage(...):` *inside* the dependency body; don't decorate.

2. **Middleware can't append to a JSON response body.** The route handler has already serialised the response before middleware's `call_next` returns. If you need to emit anything from middleware, use response **headers** and have the client capture them.

3. **`async with httpx.AsyncClient(...)` doesn't decompose cleanly for timing.** To time `__aenter__` and `__aexit__` separately, manual `client_cm = AsyncClient(...); client = await client_cm.__aenter__()` works, but you must guard `__aexit__` with an `entered = True` flag, otherwise a failed entry will call `__aexit__` on a half-initialised client.

4. **Container path assumptions.** CFN files live at `/app/src/app/...` in the running container, not `/opt/venv/lib/python3.11/site-packages/src/app/...` (which is true for many other deps in the same image). Always `find / -path '*/src/app/main.py'` first.

5. **Stack snapshots taken from a sleeping sampler miss CPU-bound wedgers.** A pure-CPU block holds the loop while the sampler is `await asyncio.sleep`-ing, then the sampler wakes up *after* the block ends and snapshots a now-idle loop. To catch CPU wedgers you'd need a signal-driven sampler. What we have catches *await-blocked* wedgers and post-wedge state, which is enough for the evidence/RAG case.

6. **Clock skew between containers on the same host is sub-millisecond.** Site 5's `wire_to_middleware_ms = wall_now_ns - X-Mycelium-Sent-Wall-Ns` is accurate to ~milliseconds because both containers share the host kernel clock. Don't bother with NTP correction; do clamp at 0 to swallow VDSO jitter.

7. **`pipeline_plus_persist_setup_ms` (an extra Site-1 stamp around the BackgroundTasks dispatch) tracks `pipeline_ms` to within 1 ms** in every observed trace — meaning persistence-task dispatch is essentially free. The hypothesis that `BackgroundTasks` setup itself was slow is dead; the wedge is in *what those tasks do once running*, not in scheduling them.

---

## Open questions

- Mycelium should also capture the new top-level `validation` field that appears on terminal responses in CFN engines #100/#101 — single new field, free.
- Test `test_41` will sometimes fail when a 50-second `wire_to_middleware_ms` blows past the round-budget tripwire — i.e. the instrumentation correctly observes the bug it was designed to find, but the test harness needs a small tolerance bump or an explicit "wedge round" carve-out so we don't lose data while reproducing.
- The pinned CFN image in `~/.mycelium/docker/compose.yml` may lag `dev/main`. When upstream lands the un-stubbed Step 4 alignment validation (an LLM call on agreed rounds), expect new latency on agreed rounds that will need its own envelope entry.
