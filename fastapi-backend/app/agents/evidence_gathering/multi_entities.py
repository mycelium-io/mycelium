"""Multi-entity evidence engine (ported from ioc-cfn-cognitive-agents).

Rewired: imports use local package paths.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np

from .embeddings import EmbeddingManager
from .llm_clients import EvidenceJudge, EvidenceRanker, get_llm_call_count
from .schemas import KnowledgeRecord, ReasonerCognitionRequest
from .utiles import mmr_select_indices


def _name_for(meta: dict[str, Any]) -> str:
    n = (meta or {}).get("name")
    return (n.strip() if isinstance(n, str) else "") or (meta or {}).get("id") or "unknown"


def _rel_label(rel: dict[str, Any]) -> str:
    return (
        str((rel or {}).get("relationship") or (rel or {}).get("relation") or "").strip()
        or "related_to"
    )


class MultiEntityConfig:
    def __init__(
        self,
        top_k_candidates: int = 2,
        max_depth: int = 4,
        pre_rank_limit: int = 20,
        mmr_top_k: int = 5,
        concurrency_limit: int = 3,
    ) -> None:
        self.top_k_candidates = top_k_candidates
        self.max_depth = max_depth
        self.pre_rank_limit = pre_rank_limit
        self.mmr_top_k = mmr_top_k
        self.concurrency_limit = concurrency_limit


@dataclass(frozen=True)
class Pair:
    source_id: str
    target_id: str
    source_name: str
    target_name: str


class MultiEntityEvidenceEngine:
    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        data_layer: Any,
        judge: EvidenceJudge,
        ranker: EvidenceRanker,
        config: MultiEntityConfig | None = None,
        concept_repo: Any = None,
    ) -> None:
        self.embedding_manager = embedding_manager
        self.data_layer = data_layer
        self.judge = judge
        self.ranker = ranker
        self.config = config or MultiEntityConfig()
        self.concept_repo = concept_repo

    def _entity_to_query_vec(self, entity: dict[str, Any]) -> list[float]:
        text = f"{entity.get('description') or ''}{entity.get('name') or ''}"
        chunks = self.embedding_manager.preprocess_text(text)
        vectors = self.embedding_manager.generate_embeddings(chunks)
        if isinstance(vectors, list) and vectors and isinstance(vectors[0], list):
            return np.mean(np.array(vectors, dtype=np.float32), axis=0).tolist()
        return np.array(vectors, dtype=np.float32).tolist()

    async def _top_k_candidates(self, entity: dict[str, Any], k: int) -> list[dict[str, Any]]:
        query_vec = self._entity_to_query_vec(entity)
        entity_name = (entity.get("name") or "").strip() or None
        enriched = await (
            self.concept_repo.similar_with_neighbors_async(query_vec, k, entity_text=entity_name)
            if self.concept_repo
            else asyncio.to_thread(self.data_layer.search_similar_with_neighbors, query_vec, k)
        )
        out: list[dict[str, Any]] = []
        for it in enriched or []:
            if (it or {}).get("concept", {}).get("id"):
                out.append(it)
            if len(out) >= k:
                break
        return out

    def _build_pairs(self, src: list[dict[str, Any]], tgt: list[dict[str, Any]]) -> list[Pair]:
        pairs: list[Pair] = []
        seen: set[tuple[str, str]] = set()
        for s in src[: self.config.top_k_candidates]:
            sc = (s or {}).get("concept") or {}
            s_id, s_name = sc.get("id"), _name_for(sc)
            if not s_id:
                continue
            for t in tgt[: self.config.top_k_candidates]:
                tc = (t or {}).get("concept") or {}
                t_id, t_name = tc.get("id"), _name_for(tc)
                if not t_id or (s_id, t_id) in seen:
                    continue
                seen.add((s_id, t_id))
                pairs.append(
                    Pair(source_id=s_id, target_id=t_id, source_name=s_name, target_name=t_name)
                )
        for t in tgt[: self.config.top_k_candidates]:
            tc = (t or {}).get("concept") or {}
            t_id, t_name = tc.get("id"), _name_for(tc)
            if not t_id:
                continue
            for s in src[: self.config.top_k_candidates]:
                sc = (s or {}).get("concept") or {}
                s_id, s_name = sc.get("id"), _name_for(sc)
                if not s_id or (t_id, s_id) in seen:
                    continue
                seen.add((t_id, s_id))
                pairs.append(
                    Pair(source_id=t_id, target_id=s_id, source_name=t_name, target_name=s_name)
                )
        return pairs

    async def gather(
        self,
        request: ReasonerCognitionRequest,
        entities: dict[str, Any],
        extra_context: str | None = None,
    ) -> KnowledgeRecord:
        e1 = {"name": entities.get("source") or ""}
        e2 = {"name": entities.get("target") or ""}
        llm_calls_before = get_llm_call_count()
        k = self.config.top_k_candidates
        src_top, tgt_top = await asyncio.gather(
            self._top_k_candidates(e1, k), self._top_k_candidates(e2, k)
        )

        trace: dict[str, Any] = {
            "extracted_entities": [e1.get("name"), e2.get("name")],
            "iterations": [],
            "sufficient": False,
            "winning": None,
            "pass_on_context": extra_context or "",
        }
        pairs = self._build_pairs(src_top, tgt_top)
        trace["lanes_count"] = len(pairs)
        sem = asyncio.Semaphore(self.config.concurrency_limit)

        async def process_pair(pair: Pair) -> dict[str, Any]:
            async with sem:
                # Fetch paths from data layer
                paths: list[dict[str, Any]] = []
                try:
                    payload = {
                        "source_id": pair.source_id,
                        "target_id": pair.target_id,
                        "max_depth": self.config.max_depth,
                        "limit": self.config.pre_rank_limit,
                    }
                    url = self.data_layer.graph_base_url + "/paths"
                    resp = await asyncio.to_thread(
                        self.data_layer.post_to_data_logic_svc, url, payload
                    )
                    if resp is not None and getattr(resp, "status_code", None) == 200:
                        j = resp.json()
                        paths = (j.get("paths") if j else []) or []
                except Exception:
                    paths = []

                # Build name mapping
                concept_ids_local: set[str] = set()
                for p in paths or []:
                    for ed in (p or {}).get("edges") or []:
                        for fid in [(ed or {}).get("from_id"), (ed or {}).get("to_id")]:
                            if fid:
                                concept_ids_local.add(fid)
                id_to_name_local: dict[str, str] = {}
                try:
                    metas = await self.data_layer.get_concepts_by_ids(list(concept_ids_local))
                    for c in metas or []:
                        cid = (c or {}).get("id")
                        if cid:
                            id_to_name_local[cid] = _name_for(c)
                except Exception:
                    pass

                candidates_symbolic = [
                    " ; ".join(
                        f"{id_to_name_local.get(ed.get('from_id')) or ed.get('from_id')} -{ed.get('relation')}-> {id_to_name_local.get(ed.get('to_id')) or ed.get('to_id')}"
                        for ed in (p or {}).get("edges") or []
                        if ed.get("from_id") and ed.get("to_id") and ed.get("relation")
                    )
                    for p in paths or []
                ]
                candidates_symbolic = [s for s in candidates_symbolic if s]
                if not candidates_symbolic:
                    return {
                        "pair": pair,
                        "paths": [],
                        "selected_indices": [],
                        "scores": {},
                        "candidates_symbolic": [],
                        "sufficient": False,
                        "reason": "no_candidate_paths",
                    }

                question_text = request.payload.intent or ""
                if extra_context:
                    question_text = f"{question_text}\n\nPrior evidence:\n{extra_context}"
                scores = await self.ranker.async_rank_paths(
                    question=question_text, candidate_paths_repr=candidates_symbolic
                )
                try:
                    chosen_idx = mmr_select_indices(
                        scores=scores,
                        candidate_texts=candidates_symbolic,
                        query_text=request.payload.intent or "",
                        embedding_manager=self.embedding_manager,
                        k=self.config.mmr_top_k,
                        alpha=0.7,
                        lam=0.7,
                    )
                except Exception:
                    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
                    chosen_idx = [int(i) for i, _ in ordered[: self.config.mmr_top_k]]
                chosen_symbolic = [
                    candidates_symbolic[i] for i in chosen_idx if 0 <= i < len(candidates_symbolic)
                ]
                _, sufficient, reason = await self.judge.async_select_paths_and_check_sufficiency(
                    question=question_text,
                    candidate_paths=chosen_symbolic,
                    select_k=len(chosen_symbolic) or 1,
                )
                return {
                    "pair": pair,
                    "paths": paths,
                    "selected_indices": chosen_idx,
                    "scores": scores,
                    "candidates_symbolic": candidates_symbolic,
                    "sufficient": bool(sufficient),
                    "reason": reason,
                }

        results = await asyncio.gather(*(process_pair(p) for p in pairs))

        winning = next((r for r in results if r.get("sufficient")), None)
        if winning:
            trace["sufficient"] = True
            trace["winning"] = {
                "source": winning["pair"].source_name,
                "target": winning["pair"].target_name,
                "reason_for_sufficiency": winning.get("reason"),
            }

        # Build evidence output
        if winning:
            r = winning
        else:
            r = max(results, key=lambda x: len(x.get("selected_indices") or []), default=None)

        evidence_paths: list[dict[str, Any]] = []
        if r and r.get("selected_indices"):
            paths_list = r.get("paths") or []
            cands = r.get("candidates_symbolic") or []
            for idx, i in enumerate(r["selected_indices"]):
                sym = cands[i] if 0 <= i < len(cands) else ""
                evidence_paths.append({"path_id": f"p{idx + 1}", "symbolic": sym})

        content = {
            "evidence": {
                "entity": {"source": {"name": e1.get("name")}, "target": {"name": e2.get("name")}},
                "status": "sufficient" if winning else "insufficient",
                "summary": {"supporting_paths": len(evidence_paths)},
                "paths": evidence_paths,
                "metadata": {"retrieval_mode": "multi_entity", "llm_assisted": True},
            },
            "trace": trace,
        }
        try:
            content["trace"]["llm_calls"] = max(0, get_llm_call_count() - llm_calls_before)  # type: ignore[index]
        except Exception:
            content["trace"]["llm_calls"] = 0  # type: ignore[index]
        return KnowledgeRecord(type="json", content=content)
