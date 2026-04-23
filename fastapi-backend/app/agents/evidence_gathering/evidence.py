# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cisco Systems, Inc. and its affiliates

"""Evidence gathering pipeline (ported from ioc-cfn-cognitive-agents).

Rewired: uses local schemas; no external dependencies/config references.
"""

from __future__ import annotations

from typing import Any

from .embeddings import EmbeddingManager
from .llm_clients import (
    EntityExtractor as LLMEntityExtractor,
)
from .llm_clients import (
    EvidenceJudge,
    EvidenceRanker,
    QueryDecomposer,
)
from .multi_entities import MultiEntityConfig, MultiEntityEvidenceEngine
from .schemas import Header, KnowledgeRecord, ReasonerCognitionRequest, ReasonerCognitionResponse
from .single_entity import ConceptRepository, SingleEntityConfig, SingleEntityEvidenceEngine
from .utiles import PathFormatter

_embedding_manager = EmbeddingManager()


async def process_evidence(
    request: ReasonerCognitionRequest,
    repo_adapter: Any = None,
    cache_layer: Any = None,
) -> ReasonerCognitionResponse:
    response_id = request.request_id
    response_header = Header(
        workspace_id=request.header.workspace_id,
        mas_id=request.header.mas_id,
        agent_id=request.header.agent_id,
    )

    entities = LLMEntityExtractor(temperature=0).extract_entities_from_request(request)
    if not entities:
        return ReasonerCognitionResponse(
            header=response_header,
            response_id=response_id,
            records=[],
            metadata={"note": "no_entities"},
        )

    try:
        ent_names = [
            str(e.get("name")).strip()
            for e in (entities or [])
            if isinstance(e, dict) and e.get("name")
        ]
    except Exception:
        ent_names = []
    n_entities = len(ent_names)
    intent = request.payload.intent or ""

    decomposition: list[dict[str, Any]] = []
    if n_entities >= 3:
        try:
            decomposition = await QueryDecomposer().async_decompose(intent, ent_names)
        except Exception:
            decomposition = []

    if n_entities == 1:
        items = [{"index": 1, "sentence": intent, "entities": ent_names}]
        mode = "single_entity"
    elif n_entities == 2:
        items = [{"index": 1, "sentence": intent, "entities": ent_names}]
        mode = "multi_entity"
    else:
        items = (
            decomposition
            if decomposition
            else [{"index": 1, "sentence": intent, "entities": ent_names[:2]}]
        )
        mode = "decomposed"

    judge = EvidenceJudge()
    ranker = EvidenceRanker()
    path_formatter = PathFormatter()
    repo = ConceptRepository(repo_adapter, cache_layer=cache_layer)
    config = SingleEntityConfig(top_k_similar=3, select_k_per_hop=3, max_depth=4)

    records_out: list[KnowledgeRecord] = []
    prior_paths: list[str] = []

    for item in items:
        _sent = str(item.get("sentence") or "").strip()
        ents = item.get("entities") or []
        extra_context = "\n".join(prior_paths[-8:]) if prior_paths else ""

        if len(ents) == 1:
            engine = SingleEntityEvidenceEngine(
                embedding_manager=_embedding_manager,
                repo=repo,
                path_formatter=path_formatter,
                judge=judge,
                ranker=ranker,
                config=config,
            )
            rec = await engine.gather(request, {"name": ents[0]}, extra_context=extra_context)
            records_out.append(rec)
            try:
                paths = (rec.content or {}).get("evidence", {}).get("paths", [])
                prior_paths.extend(
                    p.get("symbolic") for p in paths if isinstance(p, dict) and p.get("symbolic")
                )
            except Exception:
                pass
        elif len(ents) >= 2:
            me_engine = MultiEntityEvidenceEngine(
                embedding_manager=_embedding_manager,
                data_layer=repo_adapter,
                judge=judge,
                ranker=ranker,
                config=MultiEntityConfig(
                    top_k_candidates=2,
                    max_depth=4,
                    pre_rank_limit=20,
                    mmr_top_k=5,
                    concurrency_limit=3,
                ),
                concept_repo=repo,
            )
            rec = await me_engine.gather(
                request, {"source": ents[0], "target": ents[1]}, extra_context=extra_context
            )
            records_out.append(rec)
            try:
                paths = (rec.content or {}).get("evidence", {}).get("paths", [])
                prior_paths.extend(
                    p.get("symbolic") for p in paths if isinstance(p, dict) and p.get("symbolic")
                )
            except Exception:
                pass

    return ReasonerCognitionResponse(
        header=response_header,
        response_id=response_id,
        records=records_out,
        metadata={
            "mode": mode,
            "lanes": len(items),
            "returned": len(records_out),
            "request_decomposition": decomposition,
        },
    )
