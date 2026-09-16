# PR E v3: Background-task ingestion is wedging the event loop

## Summary

After PR E v2 the targeted `fastembed`/MMR wedgers are gone, but two long-tail
outliers per smoke run (~30–70 s on `cfn_decide_ms`) remain. They are **not**
caused by the AgensGraph DB writes themselves — `upsert_knowledge_graph_async`
already correctly off-loads the sync `GraphDB` work via `asyncio.to_thread`.

The actual wedger is the post-`/decide` knowledge-ingestion path that runs from
FastAPI `BackgroundTasks` **as an async coroutine on the same event loop**, and
which calls a long sequence of synchronous LLM and embedding work without any
off-load.

When the ingestion task is in-flight, every other `/decide` request lands in
uvicorn's accept queue. That backlog is what we see surface as a high
`wire_to_middleware_ms` on subsequent rounds.

## The path

`ioc-cognition-fabric-node-svc/src/app/api/semantic_nego.py:251`

```python
background_tasks.add_task(
    persist_negotiation_agreement_background,
    ...
)
```

`persist_negotiation_agreement_background` is `async def`, so FastAPI runs it
on the loop. Inside it (`semantic_nego.py:293-348`):

| step | call | nature | wedge contribution |
|---|---|---|---|
| 1 | `ConceptRelationshipExtractionService(...)` constructor | sync | small (litellm client init) |
| 2 | `KnowledgeProcessor(enable_embeddings=True, ...)` | sync | loads `fastembed` model on first use |
| 3 | `IngestDataService(...).ingest(records=[result], ...)` | **sync** | calls `_build_rag_chunks` (sync embedding) **and** `extract_concepts_and_relationships` which fires multiple **`litellm.completion(...)` sync** calls (concept extraction, relationship extraction, per-concept description distillation) — each is a 5–30 s LLM round trip |
| 4 | `processor.process(ingested_result)` | **sync** | loops over 30+ concepts calling `embedding_manager.generate_embedding(name)` — sync ONNX inference per concept |
| 5 | `await upsert_shared_memories_to_db_and_cache(...)` | async | the AgensGraph write inside is already `asyncio.to_thread`-wrapped (✅ not the wedger) |
| 6 | `vector_store.store_concepts(...)`, `store_rag_chunks(...)` (inside step 5) | sync | additional sync embedding work |

Steps 3 and 4 are what we see in the loop-lag stack snapshots, and they line
up with the log sequence we documented in the v2 results:

```
LiteLLM Wrapper: Completed Call, calling success_handler
ingestion.app.agent.service: LLM relationship extraction returned 35 relationships
ingestion.app.agent.knowledge_processor: Processed: 32 concepts, 35 relations
[WEDGE: lag=35687.0ms]
```

Translation: the LLM extraction call (sync `litellm.completion`) just
returned, the processor finished its sync embedding loop, and only then did
the loop get a chance to sample lag — which by definition is bounded below by
how long it was blocked.

## Why it shows up as queue lag on the *next* request

uvicorn runs a single worker. While the BackgroundTask coroutine holds the
loop, no `await` point yields control, so:

1. `/decide` returns 200 to the client.
2. The next `/decide` request arrives at uvicorn's socket.
3. uvicorn cannot schedule the ASGI app until the loop is free.
4. The new request sits in the accept queue for the duration of the wedge.
5. On our timing envelope this lands as `wire_to_middleware_ms ≈ wedge_ms`.

This is exactly the pattern the v2 results showed for the 58 s and 68 s
outliers.

## Recommended fix shape (PR E v3)

**Option A — minimal, low-risk (recommended for first cut):**
off-load the entire pre-DB body of the BackgroundTask to a worker thread.

```python
async def persist_negotiation_agreement_background(*, result, session_id, ...):
    def _ingest_and_process() -> dict:
        concept_service = ConceptRelationshipExtractionService(
            llm_model=LLM_MODEL,
            llm_api_key=LLM_API_KEY,
            llm_base_url=LLM_BASE_URL,
        )
        processor = KnowledgeProcessor(enable_embeddings=True, enable_dedup=False)
        ingest_service = IngestDataService(concept_service=concept_service)
        ingested = ingest_service.ingest(
            records=[result], request_id=session_id, format_descriptor="semneg",
        )
        return processor.process(ingested)

    try:
        processed_result = await asyncio.to_thread(_ingest_and_process)
        await upsert_shared_memories_to_db_and_cache(
            result=processed_result, mas_id=mas_id, workspace_id=workspace_id,
            request_id=session_id,
            vector_store=VectorStore(
                cache_layer=vector_cache_layer, rag_cache_layer=rag_cache_layer,
            ),
        )
    except Exception:
        logger.exception("Failed to persist negotiation agreement | ...")
```

This keeps the loop responsive during the LLM extraction and embedding loop,
and uses the executor we already enlarged in PR E v1 (default 64 workers).

Inside `upsert_shared_memories_to_db_and_cache` we additionally have the sync
`vector_store.store_concepts(...)` and `store_rag_chunks(...)` calls running
on the loop after the awaited DB write. Wrap those two lines in
`asyncio.to_thread` as well, in `src/app/utils/utils.py:170-171`:

```python
await asyncio.to_thread(vector_store.store_concepts, result.get("concepts", []))
await asyncio.to_thread(vector_store.store_rag_chunks, result.get("rag_chunks", []))
```

**Option B — proper, larger:** push ingestion off the FastAPI process
entirely (separate worker / queue, e.g. RQ, Celery, or a dedicated
`asyncio.Queue` consumer task in another process). This is the right
long-term shape — `/decide` responding to the client and ingestion running
on a separate worker pool decouple load on the negotiation hot path from
LLM-bound ingestion work.

We recommend shipping Option A first as a one-file (semantic_nego.py) +
two-line (utils.py) diff and validating with the standard smoke + Phase 2
batch. Option B is a larger architectural change that should be designed
separately.

## Validation plan

1. Apply Option A locally via `docker cp` + restart.
2. 2-test smoke (`test_40` + `test_41`).
3. Compare against post-v2 baseline:
   - median `cfn_decide_ms` should stay near the post-v2 value (~370 ms).
   - max `cfn_decide_ms` should drop from ~68 s into low single-digit seconds.
   - Loop-lag wedge events should disappear from CFN logs during ingestion windows.
4. Phase 2 batch (3 iters × `test_40-46`) to confirm at scale.

## What this does NOT change

- PR E v1 (executor pool size) is still required. Without it Option A's
  `asyncio.to_thread` calls would queue against CPython's default 12-worker
  pool and re-introduce thread-pool-exhaustion symptoms.
- PR E v2 (`fastembed`/MMR off-loading in the engines) is still required for
  the `/decide` hot path. v3 only addresses post-response background work.

These three layers compose: v1 sizes the pool, v2 keeps the hot path off the
loop, v3 keeps the post-response ingestion work off the loop too.
