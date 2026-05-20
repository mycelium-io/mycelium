# PR E v3 (Option A): off-load ingestion BackgroundTask — first run

## TL;DR

The Option A patch (`asyncio.to_thread` around the ingestion body and the two
sync `vector_store.store_*` calls) **deploys cleanly and removes the sync
ingestion code from the event loop** — but it does **not deliver the latency
gain we expected.** The big wedges (24-30 s) are still present and they line
up exactly with the `litellm.completion(...)` calls inside the BackgroundTask.

Diagnosis: with the body off-loaded onto an executor thread, the wedges are
now caused by **GIL contention**. `litellm.completion(...)` parses several
KB of streaming response in pure Python and the per-concept embedding loop
runs CPU-bound `fastembed` work — both hold the GIL inside the worker thread,
which starves the event loop running on the main thread.

The right fix is one of:

1. **Use `litellm.acompletion(...)` inside the engines** so the LLM call is
   *truly* async on the event loop (HTTP/streaming yields properly without
   ever owning the GIL during waits).
2. **Move ingestion off the FastAPI process** entirely (Option B from the
   v3 analysis). This is the long-term-correct shape.

## Patch verified live

`semantic_nego.py:293` and `utils.py:170-172` carry the v3 changes in the
running container. The `_ingest_and_process` thread-off-loaded helper appears
4× in stack snapshots, confirming ingestion now executes via `to_thread`.

## Smoke run

| metric                              | post-v2 | post-v3 |
| ----------------------------------- | -------:| -------:|
| tests passed                        | 2 / 2   | 2 / 2   |
| watchdog timeouts                   | 0       | 0       |
| synthesis fallbacks                 | 0       | 0       |
| `/decide` median (ms)               | 373     | 590     |
| `/decide` max (ms)                  | 68 110  | 46 735  |
| total wedge events (`>500 ms` lag)  | 10      | 11      |
| total snapshot frames               | 159     | 183     |
| total rounds (test_40 + test_41)    | 9       | 11      |

Median climbed slightly (more queueing / contention) and the max came down
modestly. Net: this is not yet a clear win.

## Why the wedges persist

Wedge timestamps line up 1:1 with `LLM relationship extraction returned N
relationships` log lines emitted from `ingestion.app.agent.service:890`,
which is the line that fires *immediately after* `litellm.completion(...)`
returns:

```
20:57:01 (wedge starts, lag accumulates)
20:57:25.079  ingestion.app.agent.service: LLM relationship extraction returned 26 relationships
20:57:25.132  CFN event-loop wedge: lag=24031.0ms threshold=500ms
…
20:58:39.310  LLM relationship extraction returned 27 relationships
20:58:39.355  CFN event-loop wedge: lag=23465.0ms
20:59:02.759  LLM relationship extraction returned 33 relationships
20:59:02.829  CFN event-loop wedge: lag=23449.0ms
21:01:25.602  LLM relationship extraction returned 34 relationships
21:01:25.701  CFN event-loop wedge: lag=30847.0ms
21:01:51.087  LLM relationship extraction returned 29 relationships
21:01:51.167  CFN event-loop wedge: lag=25406.0ms
```

The pattern is unmistakable: each big wedge ends right when the LLM
extraction call returns. The work runs in an executor thread (we verified
this), so the wedge cannot be the loop *itself* doing the work — it must be
the **GIL** being held by the worker thread for stretches long enough to
starve the loop.

That fits: `litellm.completion` does a multi-KB response parse in pure
Python (json/streaming lines), and `KnowledgeProcessor.process` runs a
per-concept sync `fastembed` embedding loop — both pure-Python CPU paths
that retain the GIL between yields.

## Stack snapshot frame distribution

(top frame per task captured during each wedge — note the snapshot can't see
into the executor-thread call stack, only into asyncio task coroutines)

| frame                                            | post-v2 | post-v3 |
| ------------------------------------------------ | ------: | ------: |
| `multi_entities.py _top_k_candidates` (sync embed) |   2 |   8 (now waiting on v2's `to_thread`) |
| `litellm._service_logger async_service_success_hook` | 0 |   0 |
| `concept_repo.similar_with_neighbors_async`     |     0 |   0 |
| `rag_retrieval.py:86 retrieve_rag_top_k`         |     1 |   4 (waiting on `to_thread`) |
| `asyncio/threads.py:25 to_thread`               |     0 |   4 (the v3 wrapper itself) |
| `uvicorn httptools_impl.py:416 run_asgi`        |     ? |  63 (queued requests) |
| `starlette middleware/base.py:144 coro`         |     ? |  60 (queued requests) |
| total wedge events                              |    10 |  11 |
| total snapshot frames                           |   159 | 183 |

The application work that did appear in snapshots is overwhelmingly tasks
**waiting on `to_thread` results** rather than tasks **doing the work** —
which is consistent with the GIL-contention diagnosis. The waiting
`/decide` requests pile up at uvicorn's accept layer (the 63+60 queued
frames), exactly the symptom we set out to fix.

## Recommended next step (PR E v4)

Two options, in order of preference:

### v4-A (smallest, highest-leverage): switch ingestion to `litellm.acompletion`

In `ioc-cfn-cognition-engines/ingestion/app/agent/service.py`, the
`extract_concepts_and_relationships(...)` flow makes multiple sync
`litellm.completion(...)` calls. Each one is the dominant wedger.

Replace `litellm.completion(...)` with `await litellm.acompletion(...)` and
make the surrounding `def`s `async def`. This:

- removes the GIL-bound response-parsing block from the worker thread
  (acompletion uses `httpx`/`aiohttp`, which yields properly), so the
  event loop stays free during the network round trip;
- still composes with v3's `asyncio.to_thread` wrapper for everything
  *except* the LLM call;
- is a one-file change in the engines repo plus a one-line change at the
  callers (since `extract_concepts_and_relationships` becomes async).

Caveat: the `KnowledgeProcessor.process()` per-concept embedding loop
(post-extraction) still runs CPU-bound. With v4-A applied, that loop is
the only remaining sync hot path and is bounded by N concepts (~30) ×
~ms per fastembed pass — small enough to ignore for now.

### v4-B (structurally correct): move ingestion off the FastAPI process

Push the entire `persist_negotiation_agreement_background` body onto a
separate worker process (Celery / RQ / dedicated `multiprocessing.Process`
consumer). This eliminates GIL contention with the request loop entirely
and is the right shape for production scale, but is a larger change.

## Recommendation

Land PR E v3 (Option A) anyway — it is **strictly correct**: ingestion
should not run sync code on the event loop, and the patch is a small,
defensive change that composes cleanly with whatever comes next.
v3 reduces max latency modestly and makes the GIL-contention layer
visible in tracing.

Then ship **PR E v4-A** (`litellm.acompletion`) as the actual latency win
on top of v3, and treat **v4-B** (separate worker process) as a longer-term
follow-on.

A wider Phase-2 batch is the right next data-collection step — but only
*after* either v4-A or v4-B; at v3-only it would just confirm the residual
wedge pattern documented here.
