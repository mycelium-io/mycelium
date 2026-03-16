"""Path utilities, GraphSession, and MMR selection (ported from ioc-cfn-cognitive-agents)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np


def select_by_relative_top(
    index_to_score: Dict[int, float],
    relative_gap: float = 0.25,
    max_k: Optional[int] = None,
) -> List[int]:
    if not index_to_score:
        return []
    sorted_items = sorted(index_to_score.items(), key=lambda kv: (-kv[1], kv[0]))
    top_idx, top_score = sorted_items[0]
    threshold = (1.0 - float(relative_gap)) * float(top_score)
    selected: List[int] = [top_idx]
    for idx, score in sorted_items[1:]:
        if score >= threshold:
            selected.append(idx)
        else:
            break
    if max_k is not None and max_k > 0:
        return selected[:max_k]
    return selected


class PathFormatter:
    @staticmethod
    def _concept_label(meta: Dict[str, Any]) -> str:
        cid = meta.get("concept_id") or meta.get("id") or ""
        name = (meta.get("name") or "").strip()
        description = (meta.get("description") or "").strip()
        label = name or (description[:60] + ("..." if len(description) > 60 else "")) or cid
        return f"{{{cid}: {label}}}" if cid else f"{{{label}}}"

    @staticmethod
    def _relation_label(rel: Dict[str, Any]) -> str:
        r = rel.get("relationship") or rel.get("relation") or ""
        return "{" + f"-> {r!s} ->" + "}"

    def to_natural_language(self, paths: List[List[Dict[str, Any]]]) -> List[str]:
        out: List[str] = []
        for path in paths:
            parts: List[str] = []
            for seg in path:
                if seg.get("kind") == "concept":
                    parts.append(self._concept_label(seg["value"]))
                elif seg.get("kind") == "relation":
                    parts.append(self._relation_label(seg["value"]))
            out.append(" - ".join(parts))
        return out

    def to_symbolic_paths(self, paths: List[List[Dict[str, Any]]]) -> List[str]:
        def _c(meta: Dict[str, Any]) -> str:
            name_raw = str((meta or {}).get("name") or "").strip()
            if name_raw:
                return name_raw.replace(" ", "_")[:64]
            desc_raw = str((meta or {}).get("description") or "").strip()
            if desc_raw:
                return (desc_raw[:64] + ("..." if len(desc_raw) > 64 else "")).replace(" ", "_")
            return "unknown"

        def _r(rel: Dict[str, Any]) -> str:
            r = str((rel or {}).get("relationship") or "").strip().upper().replace(" ", "_")
            return r or "RELATED_TO"

        out: List[str] = []
        for p_idx, path in enumerate(paths or []):
            hops: List[str] = []
            for i in range(0, max(0, len(path) - 2), 2):
                a, b, c = path[i], path[i + 1], path[i + 2]
                if a.get("kind") == "concept" and b.get("kind") == "relation" and c.get("kind") == "concept":
                    hops.append(f"{_c(a.get('value') or {})} -{_r(b.get('value') or {})}-> {_c(c.get('value') or {})}")
            out.append(f"[path_{p_idx}] " + (" ; ".join(hops) if hops else "<empty>"))
        return out


class GraphSession:
    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.relations: List[Dict[str, Any]] = []
        self.adjacency: Dict[str, List[int]] = {}

    def _ensure_node(self, meta: Dict[str, Any]) -> None:
        cid = meta.get("concept_id") or meta.get("id")
        if not cid:
            return
        if cid not in self.nodes:
            self.nodes[cid] = meta
        if cid not in self.adjacency:
            self.adjacency[cid] = []

    def _add_relation(self, relation: Dict[str, Any]) -> int:
        rel = {
            "id": relation.get("id"),
            "node_ids": list(relation.get("node_ids", [])),
            "relationship": relation.get("relationship") or relation.get("relation"),
            "attributes": relation.get("attributes"),
        }
        self.relations.append(rel)
        return len(self.relations) - 1

    def ingest_enriched_results(self, enriched: List[Dict[str, Any]]) -> None:
        for item in enriched:
            self._ensure_node(item.get("concept") or {})
            for nmeta in item.get("neighbor_concepts") or []:
                self._ensure_node(nmeta)
            for rel in item.get("relations") or []:
                idx = self._add_relation(rel)
                for nid in rel.get("node_ids", []):
                    if nid not in self.adjacency:
                        self.adjacency[nid] = []
                    self.adjacency[nid].append(idx)

    def _neighbors_for(self, concept_id: str) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        out: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for rel_idx in self.adjacency.get(concept_id, []):
            if 0 <= rel_idx < len(self.relations):
                rel = self.relations[rel_idx]
                for nid in rel.get("node_ids", []):
                    if nid and nid != concept_id:
                        nmeta = self.nodes.get(nid)
                        if nmeta:
                            out.append((rel, nmeta))
        return out

    def build_paths_from(self, start_id: Optional[str], hop: int) -> List[List[Dict[str, Any]]]:
        if not start_id or start_id not in self.nodes:
            return []
        paths: List[List[Dict[str, Any]]] = []
        start_meta = self.nodes[start_id]

        def dfs(curr_id: str, depth: int, visited: Set[str], acc: List[Dict[str, Any]]) -> None:
            if depth == hop:
                paths.append(list(acc))
                return
            for rel, nei in self._neighbors_for(curr_id):
                nid = nei.get("concept_id") or nei.get("id")
                if not nid or nid in visited:
                    continue
                acc.append({"kind": "relation", "value": rel})
                acc.append({"kind": "concept", "value": nei})
                visited.add(nid)
                dfs(nid, depth + 1, visited, acc)
                visited.remove(nid)
                acc.pop()
                acc.pop()

        dfs(start_id, 0, {start_id}, [{"kind": "concept", "value": start_meta}])
        return paths

    def add_relations_and_nodes(self, relations: List[Dict[str, Any]], neighbor_concepts: List[Dict[str, Any]]) -> None:
        for meta in neighbor_concepts or []:
            self._ensure_node(meta or {})
        for rel in relations or []:
            idx = self._add_relation(rel or {})
            for nid in (rel or {}).get("node_ids", []):
                if nid not in self.adjacency:
                    self.adjacency[nid] = []
                self.adjacency[nid].append(idx)


def generate_text_embedding(embedding_manager: object, text: str) -> np.ndarray:
    chunks = embedding_manager.preprocess_text(text or "")  # type: ignore[attr-defined]
    vecs = embedding_manager.generate_embeddings(chunks)  # type: ignore[attr-defined]
    if isinstance(vecs, list) and vecs and isinstance(vecs[0], list):
        return np.mean(np.array(vecs, dtype=np.float32), axis=0)
    return np.array(vecs, dtype=np.float32)


def normalize_l2(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0.0 else v


def mmr_select_indices(
    scores: Dict[int, float],
    candidate_texts: List[str],
    query_text: str,
    embedding_manager: object,
    k: int,
    alpha: float = 0.7,
    lam: float = 0.7,
) -> List[int]:
    k = max(1, int(k))
    n = len(candidate_texts)
    if n == 0:
        return []
    idx_list = list(range(n))
    q_vec = normalize_l2(generate_text_embedding(embedding_manager, query_text))
    d_vecs = []
    for s in candidate_texts:
        try:
            d_vecs.append(normalize_l2(generate_text_embedding(embedding_manager, s)))
        except Exception:
            d_vecs.append(np.zeros_like(q_vec, dtype=np.float32))
    if not scores:
        scores = {i: 0.5 for i in idx_list}
    sc_vals = np.array([float(scores.get(i, 0.0)) for i in idx_list], dtype=np.float32)
    sc_min, sc_max = float(sc_vals.min()), float(sc_vals.max())
    sc_norm = (sc_vals - sc_min) / (sc_max - sc_min) if sc_max > sc_min else np.ones_like(sc_vals) * 0.5
    rel = alpha * sc_norm + (1.0 - alpha) * np.array([float(np.dot(q_vec, dv)) for dv in d_vecs], dtype=np.float32)
    selected: List[int] = []
    pool = idx_list.copy()
    while len(selected) < k and pool:
        best_i, best_score = None, -1e9
        for i in pool:
            mmr_i = float(rel[i]) if not selected else float(lam * rel[i] - (1.0 - lam) * max(float(np.dot(d_vecs[i], d_vecs[j])) for j in selected))
            if mmr_i > best_score:
                best_score, best_i = mmr_i, i
        if best_i is None:
            break
        selected.append(best_i)
        pool.remove(best_i)
    return selected
