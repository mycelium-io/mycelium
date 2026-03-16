"""Single-entity evidence engine (ported from ioc-cfn-cognitive-agents).

Rewired: all imports use local package paths (no ..api.schemas, no ..config).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .embeddings import EmbeddingManager
from .llm_clients import EvidenceJudge, EvidenceRanker, get_llm_call_count
from .schemas import KnowledgeRecord, ReasonerCognitionRequest
from .utiles import (
    GraphSession,
    PathFormatter,
    mmr_select_indices,
    select_by_relative_top,
)


class SingleEntityConfig:
    def __init__(
        self,
        top_k_similar: int = 2,
        select_k_per_hop: int = 3,
        max_depth: int = 3,
        llm_temperature: float = 0.1,
    ) -> None:
        self.top_k_similar = top_k_similar
        self.select_k_per_hop = select_k_per_hop
        self.max_depth = max_depth
        self.llm_temperature = llm_temperature


class ConceptRepository:
    """Adapter over the knowledge graph / cache layer."""

    def __init__(
        self,
        repo: Any,
        cache_client: Any = None,
        cache_layer: Any = None,
        use_cache_for_similar: bool = False,
    ) -> None:
        self.repo = repo
        self.cache_client = cache_client
        self.cache_layer = cache_layer
        self.use_cache_for_similar = use_cache_for_similar

    async def similar_with_neighbors_async(
        self, query_vec: List[float], k: int, entity_text: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        use_in_memory_cache = self.cache_layer is not None
        use_http_cache = self.cache_client and self.use_cache_for_similar
        use_cache_first = use_in_memory_cache or use_http_cache

        if not use_cache_first:
            search_fn = getattr(self.repo, "search_similar_with_neighbors", None)
            if callable(search_fn):
                return await asyncio.to_thread(search_fn, query_vec, k)
            return []

        if self.cache_layer is not None:
            if entity_text and str(entity_text).strip():
                cache_results = await asyncio.to_thread(self.cache_layer.search_similar, text=str(entity_text).strip(), k=k)
            else:
                vec = np.array(query_vec, dtype=np.float32)
                if vec.ndim == 1:
                    vec = vec.reshape(1, -1)
                cache_results = await asyncio.to_thread(self.cache_layer.search_similar, vector=vec, k=k)
        elif self.cache_client:
            if entity_text and str(entity_text).strip():
                cache_results = await asyncio.to_thread(self.cache_client.search_by_text, str(entity_text).strip(), k)
            else:
                cache_results = await asyncio.to_thread(self.cache_client.search, query_vec, k)
        else:
            return []

        if not cache_results:
            return []

        concept_names: List[str] = []
        score_by_name: Dict[str, float] = {}
        cache_id_by_name: Dict[str, int] = {}
        description_by_name: Dict[str, str] = {}
        for r in cache_results:
            raw = str((r or {}).get("text") or "").strip()
            if not raw:
                continue
            name, desc = (raw.split(" | ", 1) if " | " in raw else (raw, ""))
            name, desc = name.strip(), desc.strip()
            if not name or name in score_by_name:
                continue
            concept_names.append(name)
            score_by_name[name] = float((r or {}).get("score", 0.0))
            cache_id_by_name[name] = int((r or {}).get("id", -1))
            description_by_name[name] = desc

        if not concept_names:
            return []

        out: List[Dict[str, Any]] = []
        for name in concept_names[:k]:
            neighbors_result = await self.repo.neighbors_by_name(name)
            records = (neighbors_result or {}).get("records") or []
            if not records:
                continue
            rec = records[0]
            concept = rec.get("node") or {}
            relations = [
                {"id": rel.get("id"), "node_ids": list(rel.get("node_ids", [])), "relationship": rel.get("relationship"), "attributes": rel.get("attributes")}
                for rel in rec.get("relationships") or [] if rel.get("relationship")
            ]
            neighbor_concepts = [n for n in rec.get("neighbors") or [] if n and n.get("id")]
            cid = cache_id_by_name.get(name, -1)
            concept_id = str(cid) if cid >= 0 else concept.get("id", "")
            out.append({
                "distance": score_by_name.get(name, 0.0),
                "concept": {"id": concept_id, "name": name, "description": description_by_name.get(name) or concept.get("description", ""), "type": concept.get("type", "concept")},
                "relations": relations,
                "neighbor_concepts": neighbor_concepts,
            })
        return out

    async def relations_for_async(self, concept_id: str) -> List[Dict[str, Any]]:
        result = await self.repo.neighbors(concept_id)
        rels: List[Dict[str, Any]] = []
        for rec in (result or {}).get("records", []) or []:
            for rel in rec.get("relationships", []) or []:
                rels.append({"id": rel.get("id"), "node_ids": list(rel.get("node_ids", [])), "relationship": rel.get("relationship") or rel.get("relation"), "attributes": rel.get("attributes")})
        return rels

    async def concepts_by_ids_async(self, concept_ids: List[str]) -> List[Any]:
        return await self.repo.get_concepts_by_ids(concept_ids)


@dataclass
class LaneState:
    anchor_id: str
    anchor_name: str
    graph: GraphSession
    selected_structured: List[List[Dict[str, Any]]] = field(default_factory=list)
    selected_nl: List[str] = field(default_factory=list)
    frontier_paths: List[List[Dict[str, Any]]] = field(default_factory=list)
    seen_path_keys: Set[Tuple[Any, ...]] = field(default_factory=set)
    last_candidates_structured: Optional[List[List[Dict[str, Any]]]] = None
    last_candidates_symbolic: Optional[List[str]] = None
    last_reason: Optional[str] = None
    sufficient: bool = False


def path_key(path: List[Dict[str, Any]]) -> Tuple:
    out: List[Any] = []
    for seg in path:
        if seg.get("kind") == "concept":
            out.append(("concept", (seg.get("value") or {}).get("id")))
        elif seg.get("kind") == "relation":
            out.append(("relation", (seg.get("value") or {}).get("relationship")))
    return tuple(out)


def last_edge(path: List[Dict[str, Any]], name_fn: Any, rel_fn: Any) -> Optional[Dict[str, str]]:
    for i in range(len(path) - 2, -1, -1):
        if path[i].get("kind") == "relation" and i - 1 >= 0 and i + 1 < len(path):
            prev_c = path[i - 1].get("value") or {}
            next_c = path[i + 1].get("value") or {}
            return {"from": name_fn(prev_c), "relation": rel_fn(path[i].get("value") or {}), "to": name_fn(next_c)}
    return None


def _expand_paths_one_hop(paths: List[List[Dict[str, Any]]], graph: GraphSession) -> List[List[Dict[str, Any]]]:
    next_paths: List[List[Dict[str, Any]]] = []
    for path in paths or []:
        if not path or path[-1].get("kind") != "concept":
            continue
        tail_id = (path[-1]["value"] or {}).get("id")
        if not tail_id:
            continue
        for rel, nei in graph._neighbors_for(tail_id):
            nid = (nei or {}).get("id")
            if not nid:
                continue
            visited_ids = {seg["value"].get("id") for seg in path if seg.get("kind") == "concept"}
            if nid in visited_ids:
                continue
            extended = list(path) + [{"kind": "relation", "value": rel}, {"kind": "concept", "value": nei}]
            next_paths.append(extended)
    return next_paths


class SingleEntityEvidenceEngine:
    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        repo: ConceptRepository,
        path_formatter: PathFormatter,
        judge: EvidenceJudge,
        ranker: EvidenceRanker,
        config: Optional[SingleEntityConfig] = None,
    ) -> None:
        self.embedding_manager = embedding_manager
        self.repo = repo
        self.path_formatter = path_formatter
        self.judge = judge
        self.ranker = ranker
        self.config = config or SingleEntityConfig()

    def _entity_to_query_vec(self, entity: Dict[str, Any]) -> List[float]:
        text = f"{entity.get('description') or ''}{entity.get('name') or ''}"
        chunks = self.embedding_manager.preprocess_text(text)
        vectors = self.embedding_manager.generate_embeddings(chunks)
        arr = np.array(vectors, dtype=np.float32)
        if arr.ndim == 2:
            return np.mean(arr, axis=0).tolist()
        return arr.flatten().tolist()

    async def gather(self, request: ReasonerCognitionRequest, entity: Dict[str, Any], extra_context: Optional[str] = None) -> KnowledgeRecord:
        llm_calls_before = get_llm_call_count()
        query_vec = self._entity_to_query_vec(entity)
        entity_name = (entity.get("name") or "").strip()
        enriched = await self.repo.similar_with_neighbors_async(query_vec, k=self.config.top_k_similar, entity_text=entity_name or None)

        def _name_for(meta: Dict[str, Any]) -> str:
            n = (meta or {}).get("name")
            return (n.strip() if isinstance(n, str) else "") or (meta or {}).get("id") or "unknown"

        def _rel_label(rel: Dict[str, Any]) -> str:
            return str((rel or {}).get("relationship") or (rel or {}).get("relation") or "").strip() or "related_to"

        trace: Dict[str, Any] = {
            "extracted_entity": _name_for(entity),
            "tope_similar_concepts": [],
            "iterations": [],
            "lanes_count": 0,
            "sufficient": False,
            "winning": None,
            "pass_on_context": extra_context or "",
        }

        lanes: List[LaneState] = []
        for item in enriched or []:
            concept = (item or {}).get("concept") or {}
            anchor_id = concept.get("id")
            if not anchor_id:
                continue
            g = GraphSession()
            g.ingest_enriched_results([item])
            lanes.append(LaneState(anchor_id=anchor_id, anchor_name=_name_for(concept), graph=g))

        if not lanes:
            content = {"evidence": {"entity": entity, "status": "insufficient", "paths": []}, "trace": trace}
            trace["llm_calls"] = 0
            return KnowledgeRecord(type="json", content=content)

        trace["lanes_count"] = len(lanes)
        winning_lane_index: Optional[int] = None

        for hop in range(1, self.config.max_depth + 1):
            async def select_lane(idx: int, lane: LaneState) -> Tuple:
                anchor_id = lane.anchor_id
                graph = lane.graph
                candidates_structured = (
                    graph.build_paths_from(anchor_id, hop=1)
                    if hop == 1
                    else (_expand_paths_one_hop(lane.frontier_paths, graph) if lane.frontier_paths else [])
                )
                candidates_symbolic = self.path_formatter.to_symbolic_paths(candidates_structured)
                question_text = request.payload.intent or ""
                if extra_context:
                    question_text = f"{question_text}\n\nPrior evidence:\n{extra_context}"
                chosen_idx, sufficient, reason = await self.judge.async_select_paths_and_check_sufficiency(
                    question=question_text, candidate_paths=candidates_symbolic, select_k=self.config.select_k_per_hop,
                )
                return idx, candidates_structured, candidates_symbolic, chosen_idx, sufficient, reason

            selection_tasks = [asyncio.create_task(select_lane(i, lane)) for i, lane in enumerate(lanes)]
            for fut in asyncio.as_completed(selection_tasks):
                try:
                    lane_idx, candidates_structured, candidates_symbolic, chosen_idx, sufficient, reason = await fut
                except asyncio.CancelledError:
                    continue
                lane = lanes[lane_idx]
                lane.last_candidates_structured = candidates_structured
                lane.last_candidates_symbolic = candidates_symbolic
                lane.last_reason = reason
                if sufficient and winning_lane_index is None:
                    lane.sufficient = True
                    winning_lane_index = lane_idx
                    trace["sufficient"] = True
                    trace["winning"] = {"anchor_concept": lane.anchor_name, "reason_for_sufficiency": reason}
                    for t in selection_tasks:
                        if not t.done():
                            t.cancel()
                    for t in selection_tasks:
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass
                    break

            async def rank_and_expand_lane(idx: int, lane: LaneState) -> None:
                anchor_id = lane.anchor_id
                graph = lane.graph
                candidates_structured = lane.last_candidates_structured
                candidates_symbolic = lane.last_candidates_symbolic
                if candidates_structured is None or candidates_symbolic is None:
                    candidates_structured = (
                        graph.build_paths_from(anchor_id, hop=1)
                        if hop == 1
                        else (_expand_paths_one_hop(lane.frontier_paths, graph) if lane.frontier_paths else [])
                    )
                    candidates_symbolic = self.path_formatter.to_symbolic_paths(candidates_structured)
                if not candidates_structured:
                    return
                question_text = request.payload.intent or ""
                if extra_context:
                    question_text = f"{question_text}\n\nPrior evidence:\n{extra_context}"
                scores = await self.ranker.async_rank_paths(question=question_text, candidate_paths_repr=candidates_symbolic)
                try:
                    chosen_idx = mmr_select_indices(scores=scores, candidate_texts=candidates_symbolic, query_text=request.payload.intent or "", embedding_manager=self.embedding_manager, k=self.config.select_k_per_hop, alpha=0.7, lam=0.7)
                except Exception:
                    chosen_idx = select_by_relative_top(scores, relative_gap=0.25, max_k=self.config.select_k_per_hop)
                outer_node_ids: Set[str] = set()
                for i in chosen_idx:
                    if 0 <= i < len(candidates_structured):
                        path = candidates_structured[i]
                        k_key = path_key(path)
                        if k_key not in lane.seen_path_keys:
                            lane.seen_path_keys.add(k_key)
                            lane.selected_structured.append(path)
                            nl_text = self.path_formatter.to_natural_language([path])[0] if path else ""
                            lane.selected_nl.append(nl_text)
                        if path and path[-1].get("kind") == "concept":
                            oid = (path[-1].get("value") or {}).get("id")
                            if oid:
                                outer_node_ids.add(oid)
                lane.frontier_paths = [candidates_structured[i] for i in chosen_idx if 0 <= i < len(candidates_structured)]
                if not outer_node_ids:
                    return
                rel_results = await asyncio.gather(*(self.repo.relations_for_async(oid) for oid in outer_node_ids), return_exceptions=True)
                all_relations: List[Dict[str, Any]] = []
                needed_concept_ids: Set[str] = set()
                for rels in rel_results:
                    if isinstance(rels, Exception):
                        continue
                    for rel in rels or []:
                        all_relations.append(rel)
                        for nid in rel.get("node_ids", []) or []:
                            if nid and nid not in graph.nodes:
                                needed_concept_ids.add(nid)
                neighbor_metas: List[Dict[str, Any]] = []
                if needed_concept_ids:
                    try:
                        neighbor_metas = await self.repo.concepts_by_ids_async(list(needed_concept_ids))
                    except Exception:
                        neighbor_metas = []
                graph.add_relations_and_nodes(all_relations, neighbor_metas)

            if winning_lane_index is not None:
                await rank_and_expand_lane(winning_lane_index, lanes[winning_lane_index])
                break
            else:
                await asyncio.gather(*(rank_and_expand_lane(i, lane) for i, lane in enumerate(lanes)))

        if winning_lane_index is not None:
            wl = lanes[winning_lane_index]
            selected_structured = wl.selected_structured
            sufficient = True
        else:
            selected_structured = []
            sufficient = False

        evidence_paths: List[Dict[str, Any]] = []
        for idx, path in enumerate(selected_structured or []):
            try:
                symbolic = self.path_formatter.to_symbolic_paths([path])[0]
            except Exception:
                symbolic = ""
            evidence_paths.append({"path_id": f"p{idx+1}", "symbolic": symbolic})

        content = {
            "evidence": {
                "entity": entity,
                "status": "sufficient" if sufficient else "insufficient",
                "summary": {"supporting_paths": len(evidence_paths)},
                "paths": evidence_paths,
                "metadata": {"retrieval_mode": "single_entity", "llm_assisted": True},
            },
            "trace": trace,
        }
        try:
            trace["llm_calls"] = max(0, get_llm_call_count() - llm_calls_before)
        except Exception:
            trace["llm_calls"] = 0
        return KnowledgeRecord(type="json", content=content)
