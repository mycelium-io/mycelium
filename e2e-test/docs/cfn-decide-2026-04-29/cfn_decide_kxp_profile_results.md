# CFN /decide latency — KXP / AgensGraph wedge profiling

Date: 2026-04-26
Scope: 1-hour profiling cycle requested after PR E v4-B-batch shipped.
Goal: Confirm or rule out `upsert_knowledge_graph_async` (AgensGraph
synchronous SQLAlchemy / psycopg2 save loop) as the source of the
remaining 25–35 s event-loop wedges in CFN.

## TL;DR

**The N+1 SQL hypothesis was wrong.**
`db.save()` in `knowledge_memory` is **not** the wedge. With explicit
phase timing instrumented around every loop in
`KnowledgeGraphService.create_graph_store` → `GraphDB.save()`, two real
saves observed during the smoke run completed in **582 ms** and
**697 ms** total, while wedges of 23–37 s continued to fire during the
same window. Crucially, **wedges fire during ingests that never reach
`db.save()`** — they line up with the LLM extraction phase, not the
graph save phase.

Recommended next step: do **not** invest in batching `db.save()` (low
leverage, ~500 ms/ingest at most). Instead pursue **PR E v4-C process
isolation for the whole ingest BackgroundTask** or a cheap front-of-line
mitigation (ingest semaphore + thread-pool partitioning) — the wedges
are GIL-contention from the LLM/fastembed/JSON pipeline running in the
shared `to_thread` pool while concurrent `/decide` workers also hold the
GIL.

## Method

1. Patched `GraphDB.save()` in
   `src/server/database/graph_db/agensgraph/src/db.py` to log
   per-phase elapsed times for every successful save:
   - `connect+set_path_ms`
   - `exists_nodes_ms` / `exists_nodes_n`
   - `exists_edges_ms` / `exists_edges_n`
   - `create_nodes_ms` / `create_nodes_n`
   - `create_edges_ms` / `create_edges_n`
   - `total_ms`
2. Deployed via `docker cp` into the running
   `ioc-cognition-fabric-node-svc` container at
   `/opt/venv/lib/python3.11/site-packages/knowledge_memory/server/database/graph_db/agensgraph/src/db.py`
   and restarted the container.
3. Re-ran the same smoke pair used for v4-B-batch:
   `tests/test_mycelium_e2e.py::test_40_distributed_two_agent` and
   `::test_41_distributed_three_agent`. Both passed (324.95 s wall).
4. Mined `docker logs` for `KXP_PROFILE` lines, plus
   `Successfully converted to N nodes and M edges`,
   `Successfully saved …`, `Force replace enabled …`, and CFN
   loop-lag wedge events.

## Phase-time results

Two saves actually entered the `force_replace=True` branch and reached
the instrumentation:

| graph (suffix) | exists_n | exists_e | exists_n_ms | exists_e_ms | create_n_ms | create_e_ms | total_ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| `…129abdee…` | 33 | 52 | 9.0 | 40.8 | 65.8 | 462.3 | **582.3** |
| `…888d273f…` | 24 | 46 | 7.9 | 48.2 | 59.2 | 575.4 | **697.3** |

Per-record averages of the slowest phase (`create_edges_ms`) work out
to **8.9 ms/edge** and **12.5 ms/edge** respectively — fully consistent
with normal psycopg2/AgensGraph round-trip cost; nothing pathological.

## Wedge ↔ save correlation

During the same ~5 minute test window the loop-lag sampler logged the
following wedges (>500 ms threshold):

```
23:42:52.071  lag=27251 ms
23:43:02.776  lag=1621 ms
23:43:05.660  lag=2868 ms
23:43:06.846  lag=1173 ms
23:44:12.147  lag=33154 ms
23:44:49.719  lag=37550 ms
23:44:57.483  lag=1069 ms
23:45:52.845  lag=1198 ms
23:45:55.716  lag=2855 ms
23:46:42.867  lag=23499 ms
23:47:16.591  lag=29139 ms
23:47:27.386  lag=1596 ms
```

Pairing each "Successfully converted to N nodes and M edges" event
with its companion save log:

| convert ts | nodes | edges | save log? | KXP_PROFILE total | wedge nearby |
|---|---:|---:|---|---|---|
| 23:42:52.061 | 27 | 38 | no | — | **27.3 s @ 23:42:52.071** |
| 23:44:12.135 | 35 | 38 | no | — | **33.2 s @ 23:44:12.147** |
| 23:44:49.699 | 44 | 49 | no | — | **37.6 s @ 23:44:49.719** |
| 23:45:27.661 | 33 | 52 | yes | **582 ms** | none |
| 23:46:42.871 | 22 | 24 | no | — | **23.5 s @ 23:46:42.867** |
| 23:47:16.578 | 25 | 32 | no | — | **29.1 s @ 23:47:16.591** |
| 23:47:54.887 | 24 | 46 | yes | **697 ms** | none |

The two saves that did execute did **not** produce wedges. The wedges
fire on ingests that stop before reaching `db.save()` (most ingests
fall in the `force_replace=False` path, hit the existing-nodes
short-circuit, and never enter the create loops).

## What the wedge actually is

Reconstructing the 23:42 wedge window from the log timeline:

```
23:42:24.818  RAG cache miss; creating new RAG cache layer
23:42:24.819  Loading embedding model from local path: …granite-embedding-30m-english   (KnowledgeProcessor init)
23:42:24.980  Filtered to 2 records from 1 total (format=openclaw)
23:42:25.063  Loading embedding model …                                                  (second instance — vector store init)
23:42:25.434  Generated 4 rag chunks (format=openclaw)
23:42:25.447  LiteLLM completion() model= bedrock/global.anthropic.claude-haiku-4-5… provider = openai
23:42:52.024  Wrapper: Completed Call, calling success_handler
23:42:52.024  LLM relationship extraction returned 38 relationships
23:42:52.050  Processed: 27 concepts, 38 relations
23:42:52.060  Processing 27 concepts                          (adapter_graphdb_agensgraph)
23:42:52.061  Successfully converted to 27 nodes and 38 edges
23:42:52.070  Graph 'graph_…' already exists                  (db.create_graph)
23:42:52.071  CFN event-loop wedge: lag=27251 ms threshold=500 ms running_tasks=9
```

The LLM call from 23:42:25.447 → 23:42:52.024 spans **26.6 s**, which
matches the 27.3 s lag almost exactly (allowing for the 0.3 s of
`logger.info` activity that happened between 23:42:24.8 and 23:42:25.4
before the LLM round trip began).

LiteLLM logs `provider = openai` — this routes through the
`LLM_BASE_URL` OpenAI-compatible proxy via `httpx.AsyncClient`, not the
raw Bedrock SDK, so `acompletion` is *meant* to be truly non-blocking.
Yet the loop sampler did not tick for 27 s, and the wedge stack snapshots
captured at 23:42:52.072 show only outer Uvicorn/Starlette/registration
frames (`uvicorn/server.py:79`, `starlette/middleware/base.py:139`,
`registration.py:145`). No task is observed mid-flight inside the LLM
client. That points at the classic GIL-contention symptom: while the
LLM `await` is suspended, **other workers hold the GIL** and prevent the
sampler coroutine from being scheduled — even though the LLM coroutine
itself is happily awaiting on a socket.

The "other workers" during ingest:

- `processor.process(...)` (already off-loop via `asyncio.to_thread`,
  but still pure-Python: dedup loop, type building, dict merging — all
  GIL-bound).
- `EmbeddingManager.generate_embeddings_batch(...)` — fastembed/ONNX
  inference. After v4-B-batch this is one big `embed()` call, but it
  still releases the GIL only at C-extension boundaries; pre/post
  Python work holds it.
- Concurrent `/decide` workers running FAISS query, MMR re-rank, and
  vector marshalling in `to_thread` (we offloaded those in PR E v2).
- Per-request `KnowledgeProcessor` and `VectorStore` instantiations
  load the embedding model from disk on every ingest — log shows two
  loads back-to-back (~240 ms + ~370 ms), all on the event loop and
  all GIL-bound.

`running_tasks` on the wedges climbs in lockstep with concurrency:
`9` at the first wedge, `12–17` mid-test, `21–27` at the peak. That is
the characteristic shape of GIL contention from many concurrent
worker-thread tasks.

## What this rules out and rules in

Rules **out**:

- AgensGraph N+1 round-trips as the wedge cause. `db.save()` runs in
  580–700 ms total even with 33–52 nodes + edges and ~178 sequential
  Cypher round-trips — about 8–12 ms/round-trip, fully expected for
  in-process psycopg2. Even in worst-case ingest sizes from prior
  v4-B-batch runs (39 nodes / 50 edges) the projected save cost is
  ~700 ms, not 30 s.
- Synchronous SQLAlchemy / psycopg2 result marshaling as a meaningful
  GIL hog. psycopg2 releases the GIL during the network/socket portion
  of every round-trip; the small per-row Python work between trips is
  not the bottleneck.

Rules **in**:

- The wedge is GIL contention in CFN's main `to_thread` worker pool
  during the ingest pipeline. The dominant components are LLM
  pre/post-processing (JSON marshaling, Pydantic validation), embedding
  generation (Python around the fastembed C calls), and concurrent
  `/decide` work that shares the same pool.
- Per-request embedding-model construction is itself non-trivial work
  on the event loop; both `KnowledgeProcessor` and `VectorStore`
  instantiate their own model and call `Loading embedding model …`
  on every ingest.

## Recommended next steps

1. **Drop the AgensGraph batching idea.** Even an optimal UNWIND-style
   bulk save would only buy ~500 ms; it has no measurable effect on the
   25–35 s wedges. Mark `v4b-pool` and any related "KXP rewrite" line
   items closed.
2. **Pursue PR E v4-C: process-isolated ingest BackgroundTask.**
   This is the only thing that breaks GIL contention with `/decide`.
   The full picture of what to move into the worker process:
   - the per-request `ConceptRelationshipExtractionService` /
     `KnowledgeProcessor` / `IngestDataService` constructors,
   - `ingest_async()` (LLM round trips run in the worker process; this
     also makes any LiteLLM-internal sync work harmless),
   - `processor.process(...)` (dedup, embed, dict marshaling),
   - `upsert_shared_memories_to_db_and_cache(...)` including the in-process
     KXP `db.save()` call.

   Open questions for v4-C:
   - Pickle the worker payload — `result`, `mas_id`, `workspace_id`,
     `session_id` are all simple dicts/strings. The cache layers
     (`vector_cache_layer`, `rag_cache_layer`) are in-memory FAISS /
     state objects that are **not** picklable; the worker needs to
     re-resolve them from the per-MAS singleton inside the new
     process. Easiest path: have the worker call the same factory
     (`get_or_create_vector_cache_layer(...)`) so it builds its own
     local instance. This means the FAISS index in the worker is a
     separate copy — acceptable as long as the worker writes back to
     the canonical store (Postgres + cache backing file).
   - Embedding model warmup — preload `granite-embedding-30m-english`
     in the `initializer=` callback so the first request doesn't pay
     the load cost.
   - Lifecycle — long-lived `ProcessPoolExecutor(max_workers=2..4)`
     created in CFN startup; plumbed via dependency injection. Avoid
     spawning new workers per request.

3. **Cheap front-of-line mitigation** (do whether or not v4-C lands):
   - Add a small `asyncio.Semaphore` around the ingest BackgroundTask
     so at most 1–2 ingests run concurrently per CFN. With the current
     test load (2–3 agents) this alone should cap wedge depth.
   - Hoist the embedding model load out of the per-request
     constructors. Cache one `EmbeddingManager` per CFN process.
     Removes ~600 ms of on-event-loop work per ingest immediately.

4. Keep the `KXP_PROFILE` instrumentation in place behind a logger
   level / env-flag — it's quick, low-cost, and gives a permanent
   answer if the AgensGraph hypothesis ever resurfaces.

## Files touched (instrumentation only — not committed)

- `src/server/database/graph_db/agensgraph/src/db.py`
  (`/opt/venv/lib/.../knowledge_memory/.../db.py` inside the CFN container)
  — added `KXP_PROFILE save graph=… …` log line plus per-phase timing
  with `time.perf_counter()`.

The change is contained to four loops in `GraphDB.save()`; revert is a
straight `docker cp` of the upstream file.

## Addendum — Cost/scope of v4-C vs cheap mitigations

Added 2026-04-27 in response to "is v4-C really a lot of changes?".
Short answer: yes, meaningfully more than it looks. The executor wiring
is small; the FAISS cache-coherency problem is what makes it a multi-day
change. The cheap mitigations from "Recommended next steps" item 3 are
~half a day and may obviate v4-C entirely.

### What v4-C actually requires

Mechanical pieces (easy, ~half a day):

- Create a long-lived `ProcessPoolExecutor` at CFN startup with an
  `initializer=` that:
  - bootstraps `knowledge_memory.ConnectDB` so the worker has its own
    AgensGraph connection,
  - configures LiteLLM env (`LLM_API_KEY`, `LLM_BASE_URL`, model id),
  - pre-loads the fastembed model (otherwise the first request in each
    worker pays a ~1 s cold load).
- Promote the BackgroundTask body to a module-level picklable function
  `_ingest_job(payload_dict)`.
- Replace
  `await ingest_service.ingest_async(...)` →
  `await asyncio.to_thread(processor.process, ...)` →
  `await upsert_shared_memories_to_db_and_cache(...)`
  with a single
  `await loop.run_in_executor(pool, _ingest_job, payload)`.
- Plumb logging from worker → parent (QueueHandler or rely on stderr
  inheritance with a structured formatter).

Hard part — FAISS cache coherency:

`upsert_shared_memories_to_db_and_cache(...)` writes into
`vector_cache_layer` and `rag_cache_layer`, which are **in-memory
per-MAS FAISS singletons living in the CFN parent process**. Those
objects are not picklable, and even if they were, the worker would
only mutate its own copy. So after an ingest in the worker:

- Postgres / AgensGraph: correct (external DB).
- Worker's FAISS index: has the new vectors, but is thrown away when
  the future returns.
- **Parent's FAISS index (the one `/decide` queries): does NOT see the
  new concepts** until the next cache warmup re-reads from Postgres.

That's a regression. Three ways to fix it, in increasing scope:

1. Have the worker return `(concept_id, vector, payload)` tuples and
   the parent re-inserts them into its own FAISS index when the future
   resolves. Cheap-ish, but you're back to doing FAISS work on the
   event loop — partly defeats the purpose.
2. Move `vector_cache_layer` / `rag_cache_layer` out of process-local
   memory entirely (e.g., shared FAISS over a sidecar / Redis-vector
   / persisted index re-mmap). Much bigger lift; touches every read
   path too.
3. Accept stale FAISS until the next periodic warmup. Likely breaks
   `/decide` semantics for freshly-agreed concepts in tests like
   `test_45_distributed_preexisting_context`.

Option 1 is the realistic path; it adds a small but real return-channel
design plus tests.

Additional risk surface:

- Pickle errors on first deploy when Pydantic / litellm internals leak
  into the payload — needs payload normalisation upfront.
- Workers dying mid-ingest leave Postgres in a partial state — need a
  worker-restart / partial-rollback story.
- Per-MAS FAISS state in the worker either has to be rebuilt every
  call (slow) or kept warm via sticky-mas routing of futures to the
  same worker.

End-to-end scope estimate: ~2–3 days including tests.

### Cheap mitigations (item 3 of "Recommended next steps")

Two small changes, low risk, no semantics change:

1. Ingest semaphore around the BackgroundTask:

   ```python
   _INGEST_SEM = asyncio.Semaphore(2)

   async def persist_negotiation_agreement_background(...):
       async with _INGEST_SEM:
           ...
   ```

   Caps stacked ingests, directly addressing the `running_tasks`
   climbing to `27` we saw in the wedge log.

2. Hoist the embedding model out of per-request constructors. Cache one
   `EmbeddingManager` per CFN process (module-level singleton or
   `functools.lru_cache`). `KnowledgeProcessor` and `VectorStore`
   currently each load the model on every ingest — the wedge log shows
   two `Loading embedding model from local path` lines per request,
   ~240 ms + ~370 ms, both on the event loop.

Combined edit footprint is roughly 15–30 lines across two files.

### Suggested order

1. Ship cheap mitigations first (semaphore + cached embedding model).
   ~Half a day, low risk. Re-measure with the same smoke pair
   (`test_40_distributed_two_agent`, `test_41_distributed_three_agent`).
2. If wedges are still > 5 s p95 after that, commit to v4-C and budget
   for the FAISS return-channel — that's the part to scope carefully.
3. If wedges drop to a tolerable band (e.g. < 3 s p95), defer v4-C
   indefinitely.

The cheap mitigations are independently useful even if v4-C eventually
lands — the embedding-model singleton is just hygiene, and the
semaphore is a reasonable production guardrail in any architecture.
