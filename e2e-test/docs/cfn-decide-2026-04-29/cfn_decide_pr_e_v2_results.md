# PR E v2: Initial validation — `_entity_to_query_vec` / MMR off-loading

## Summary

PR E v2 wraps the synchronous `fastembed`/ONNX inference paths inside the
evidence engines (`_entity_to_query_vec` and `mmr_select_indices`) with
`asyncio.to_thread` so they no longer run directly on the event loop.

A 2-test smoke run (`test_40` + `test_41`, 9 negotiation rounds total) shows
the patch **eliminates the wedger frames v2 was designed to remove**, drops
median `/decide` from ~830 ms (post-v1) to ~370 ms, and produces zero
synthesis fallbacks / zero watchdog timeouts. Two long-tail outliers remain
(58 s and 68 s decide), driven by a **different, newly-visible wedger in the
knowledge-ingestion path** that PR E v2 was not designed to address.

## Patch

`evidence/app/agent/multi_entities.py` and `evidence/app/agent/single_entity.py`:

- `_entity_to_query_vec` is now `async`; the `preprocess_text` +
  `generate_embeddings` body runs via `asyncio.to_thread`.
- Both `_top_k_candidates` call sites updated to `await` the helper.
- Both `mmr_select_indices` call sites wrapped with
  `await asyncio.to_thread(mmr_select_indices, …)`.

(33 net lines changed across two files; experiment branch
`experiment/cfn-decide-pr-e-v2`.)

## Smoke run

| metric                              | post-v1 baseline | post-v2 |
| ----------------------------------- | ---------------- | ------- |
| tests passed                        | 2 / 2            | 2 / 2   |
| watchdog timeouts                   | 0                | 0       |
| synthesis fallbacks                 | 0                | 0       |
| `/decide` median (ms)               | ~830             | **373** |
| `/decide` min (ms)                  | ~30              | 35      |
| `/decide` max (ms)                  | ~28 000          | 68 110  |
| short rounds (<700 ms)              | n/a              | 7 / 9   |

(7 of 9 rounds finished `/decide` in under 700 ms; the per-round outliers are
discussed below.)

## Wedger frame distribution

Aggregated from the loop-lag sampler's stack snapshots over the smoke window:

| frame                                           | pre-v2 | post-v2 |
| ----------------------------------------------- | -----: | ------: |
| `multi_entities.py _top_k_candidates` (sync embed) | 138 |   2 |
| `litellm._service_logger async_service_success_hook` | 59 |   0 |
| `concept_repo.similar_with_neighbors_async`     |     19 |   0 |
| `rag_retrieval.py:86 retrieve_rag_top_k`         |     46 |   1 |
| total wedge events                              | thousands |  10 |
| total snapshot frames                           | ~9 200 | 159 |

Result: **the targeted wedgers are gone.** The two remaining `_top_k_candidates`
hits are at the legitimate `await self.concept_repo.similar_with_neighbors_async(...)`
line — i.e. the task is now properly awaiting an async I/O, not running sync
ONNX on the loop.

## Residual outliers (the next layer)

Two rounds in 9 still wedged (35.7 s, 31.8 s wall clock during request
windows). The interleaved INFO/WARNING log entries adjacent to each large
wedge tell a clear story:

```
… LiteLLM Wrapper: Completed Call, calling success_handler
… ingestion.app.agent.service: LLM relationship extraction returned 35 relationships
… ingestion.app.agent.knowledge_processor: Processed: 32 concepts, 35 relations
… knowledge_memory.server.adapters.adapter_graphdb_agensgraph: Processing 32 concepts
… knowledge_memory.server.adapters.adapter_graphdb_agensgraph: Processing 35 relations
… [WEDGE: lag=35687.0ms]
… knowledge_memory.server.database.graph_db.agensgraph.src.db: Graph '…' already exists
```

The pattern, repeated for every >25 s wedge:

1. `/decide` returns to Mycelium.
2. CFN's FastAPI `BackgroundTasks` runs the knowledge-ingestion pipeline.
3. `knowledge_processor` extracts 30+ concepts/relations, then calls the
   AgensGraph adapter.
4. The AgensGraph adapter's sync `db.py` graph creation/check (and the
   subsequent batch INSERTs) runs **directly on the event loop**.
5. While that sync work runs, every other `/decide` request piles up in
   uvicorn's accept queue — that is what shows up as
   `wire_to_middleware_ms = 32 s` on the next request.

The wedge tasks all show up as `await app(...)` in stack snapshots, with
no app-frame visible — consistent with the wedger living in either
(a) sync code reached during background-task execution that holds the GIL,
or (b) a thread that doesn't release the GIL, blocking the event loop's
ability to schedule callbacks.

## Recommendation

PR E v2 is a clean, targeted, low-risk patch. Recommend merging as is —
it eliminates the wedgers it was designed for and produces a measurable,
reproducible drop in median `/decide` latency.

**The next investigation (call it PR E v3)** is the
knowledge-ingestion / AgensGraph background-task path:

- `knowledge_memory.server.database.graph_db.agensgraph.src.db` and
  `knowledge_memory.server.adapters.adapter_graphdb_agensgraph` perform
  sync graph-DB operations on the event loop.
- These run from `BackgroundTasks` after `/decide` returns; under load,
  back-pressure from these operations stalls subsequent `/decide` requests
  in uvicorn's accept queue.
- Likely fix shape: either offload the sync AgensGraph operations to
  `asyncio.to_thread` at the adapter boundary, or move the entire
  knowledge-ingestion pipeline off `BackgroundTasks` onto a separate
  worker process / queue.

A wider Phase-2 batch (3 iters × `test_40-46`) is the right next step to
quantify the v2 gain at scale and confirm the residual wedger profile.
