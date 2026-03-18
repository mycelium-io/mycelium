"""LLM clients for evidence gathering (ported from ioc-cfn-cognitive-agents).

Rewired: uses Azure OpenAI when AZURE_OPENAI_* env vars are set; graceful
fallbacks throughout so the backend starts without any Azure credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import ClassVar

_LLM_CALL_COUNT = 0


def get_llm_call_count() -> int:
    return _LLM_CALL_COUNT


def _inc_llm_call_count() -> None:
    global _LLM_CALL_COUNT
    _LLM_CALL_COUNT += 1


class _LLMBaseClient:
    def __init__(self, temperature: float, client_label: str) -> None:
        self.temperature = temperature
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        self._azure_client = None
        if self.endpoint and self.api_key and self.deployment:
            try:
                from openai import AzureOpenAI  # type: ignore[import-untyped]

                self._azure_client = AzureOpenAI(
                    api_key=self.api_key,
                    api_version=self.api_version or "2024-06-01",
                    azure_endpoint=self.endpoint,
                )
            except Exception:
                self._azure_client = None

    def _call_chat(self, system: str, user: str) -> str:
        if not self._azure_client:
            raise RuntimeError("Azure client not configured")
        resp = self._azure_client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature,
        )
        _inc_llm_call_count()
        return (resp.choices[0].message.content or "").strip()


class EvidenceJudge(_LLMBaseClient):
    def __init__(self, temperature: float = 0.2) -> None:
        super().__init__(temperature=temperature, client_label="EvidenceJudge")

    def select_paths_and_check_sufficiency(
        self, question: str, candidate_paths: list[str], select_k: int
    ) -> tuple[list[int], bool, str]:
        if not candidate_paths:
            return [], False, ""
        if not self._azure_client:
            k = min(select_k, len(candidate_paths))
            return list(range(k)), False, "fallback: azure not configured"
        system = (
            "You are an evidence-based reasoning judge selecting the most relevant knowledge paths "
            "to answer a query.\n"
            "Respond with STRICT JSON ONLY:\n"
            '  {"selected": [indices], "sufficient": true|false, "reason": "<one-line>"}\n'
            '- "selected" is 0-based integer indices.\n'
            "- Do not include trailing commas, comments, or extra fields."
        )
        numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(candidate_paths))
        user = f"Question: {question or '(none)'}\n\nCandidate paths:\n{numbered}\n\nSelect top {select_k} paths."
        try:
            content = self._call_chat(system, user)
            data = json.loads(content)
            selected = [
                i
                for i in (data.get("selected") or [])
                if isinstance(i, int) and 0 <= i < len(candidate_paths)
            ]
            sufficient = bool(data.get("sufficient", False))
            reason = (
                str(data.get("reason") or "").splitlines()[0].strip() if data.get("reason") else ""
            )
            return selected[:select_k], sufficient, reason
        except Exception:
            k = min(select_k, len(candidate_paths))
            return list(range(k)), False, "fallback: azure error"

    async def async_select_paths_and_check_sufficiency(
        self, question: str, candidate_paths: list[str], select_k: int
    ) -> tuple[list[int], bool, str]:
        return await asyncio.to_thread(
            self.select_paths_and_check_sufficiency, question, candidate_paths, select_k
        )


class EvidenceRanker(_LLMBaseClient):
    def __init__(self, temperature: float = 0.2) -> None:
        super().__init__(temperature=temperature, client_label="EvidenceRanker")

    def rank_paths(self, question: str, candidate_paths_repr: list[str]) -> dict[int, float]:
        if not candidate_paths_repr:
            return {}
        n = len(candidate_paths_repr)
        if not self._azure_client:
            return {i: 1.0 - 0.5 * (i / (n - 1)) for i in range(n)} if n > 1 else {0: 1.0}
        system = (
            "You are ranking knowledge paths by relevance to a question (0.0-1.0 scale).\n"
            "Respond with STRICT JSON ONLY:\n"
            '  {"scores": [{"index": i, "score": number}]}\n'
            "- Do not include trailing commas, comments, or extra fields."
        )
        numbered = "\n".join(f"{i}. {p}" for i, p in enumerate(candidate_paths_repr))
        user = (
            f"Question: {question or '(none)'}\n\nCandidate paths:\n{numbered}\n\nRank all items."
        )
        try:
            content = self._call_chat(system, user)
            data = json.loads(content)
            scores: dict[int, float] = {}
            for item in data.get("scores") or []:
                try:
                    idx = int(item.get("index"))
                    sc = max(0.0, min(1.0, float(item.get("score"))))
                    if 0 <= idx < n:
                        scores[idx] = sc
                except Exception:
                    continue
            if not scores:
                return {i: 1.0 - 0.5 * (i / (n - 1)) for i in range(n)} if n > 1 else {0: 1.0}
            return scores
        except Exception:
            return {i: 1.0 - 0.5 * (i / (n - 1)) for i in range(n)} if n > 1 else {0: 1.0}

    async def async_rank_paths(
        self, question: str, candidate_paths_repr: list[str]
    ) -> dict[int, float]:
        return await asyncio.to_thread(self.rank_paths, question, candidate_paths_repr)


class EntityExtractor(_LLMBaseClient):
    SYSTEM_PROMPT = (
        "You extract salient entities from the user's intent and any provided text.\n"
        "Respond with STRICT JSON ONLY:\n"
        '  {"entities": [{"name": "<entity-1>"}, ...]}\n'
        "- Do not include trailing commas, comments, or extra fields."
    )
    STOPWORDS: ClassVar[set[str]] = {
        "what",
        "does",
        "do",
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "for",
        "in",
        "on",
        "with",
        "is",
        "are",
    }

    def __init__(self, temperature: float = 0.1) -> None:
        super().__init__(temperature=temperature, client_label="EntityExtractor")

    def _fallback_extract(self, intent: str, texts: list[str]) -> list[dict]:
        import re

        combined = f"{intent} {' '.join(texts)}".lower()
        candidates = re.findall(r"[a-z][a-z0-9_-]{3,}", combined)
        keywords = []
        seen: set = set()
        for w in candidates:
            if w in self.STOPWORDS or w in seen:
                continue
            seen.add(w)
            keywords.append({"name": w})
            if len(keywords) >= 10:
                break
        return keywords or ([{"name": intent.strip()}] if intent.strip() else [])

    def extract_entities_from_request(self, request: object) -> list[dict]:
        intent = getattr(getattr(request, "payload", None), "intent", "") or ""
        texts: list[str] = []
        for rec in getattr(getattr(request, "payload", None), "records", None) or []:
            try:
                rt = (
                    rec.record_type.value
                    if hasattr(rec, "record_type") and hasattr(rec.record_type, "value")
                    else str(getattr(rec, "record_type", ""))
                )
            except Exception:
                rt = ""
            if rt == "string" and isinstance(getattr(rec, "content", None), str):
                texts.append(rec.content)
            elif rt == "json":
                texts.append(json.dumps(rec.content, ensure_ascii=False, separators=(",", ":")))
        if not self._azure_client:
            return self._fallback_extract(intent, texts)
        user_prompt = f"INTENT:\n{intent}\n\nTEXT:\n" + ("\n".join(texts) if texts else "(none)")
        try:
            content = self._call_chat(self.SYSTEM_PROMPT, user_prompt)
            data = json.loads(content)
            ents = data.get("entities") if isinstance(data, dict) else data
            return [
                {"name": e.get("name", "").strip()}
                for e in ents
                if isinstance(e, dict) and e.get("name")
            ]
        except Exception:
            return self._fallback_extract(intent, texts)

    async def async_extract_entities_from_request(self, request: object) -> list[dict]:
        return await asyncio.to_thread(self.extract_entities_from_request, request)


class QueryDecomposer(_LLMBaseClient):
    SYSTEM_PROMPT = (
        "Break a multi-hop question into simpler parts using up to two topic entities each.\n"
        "OUTPUT FORMAT (strict):\n"
        "- Generate lines: #(number). (query) , ##entity1##entity2##\n"
        "- Do not include any extra text outside the numbered lines."
    )

    def __init__(self, temperature: float = 0.2) -> None:
        super().__init__(temperature=temperature, client_label="QueryDecomposer")

    def decompose(self, text: str, entities: list[str] | None = None) -> list[dict]:
        if not (text or "").strip():
            return []
        if not self._azure_client:
            return [{"index": 1, "sentence": (text or "").strip(), "entities": []}]
        safe_ents = [str(e).strip() for e in (entities or []) if str(e).strip()]
        system_content = self.SYSTEM_PROMPT
        if safe_ents:
            system_content += "\n\nTopic entities:\n- " + "\n- ".join(safe_ents)
        try:
            content = self._call_chat(system_content, f"Sentence:\n{text}".strip())
        except Exception:
            return [{"index": 1, "sentence": (text or "").strip(), "entities": []}]
        out: list[dict] = []
        for line in (content or "").splitlines():
            line = line.strip()
            if not line or not line.startswith("#"):
                continue
            parts = line.split("##")
            parsed_entities = [
                parts[i].strip() for i in range(1, len(parts), 2) if parts[i].strip()
            ][:2]
            sent_part = parts[0]
            dot_pos = sent_part.find(".")
            if dot_pos != -1:
                sent_part = sent_part[dot_pos + 1 :].strip(" ,")
            else:
                space_pos = sent_part.find(" ")
                if space_pos != -1:
                    sent_part = sent_part[space_pos + 1 :].strip(" ,")
            out.append(
                {"index": len(out) + 1, "sentence": sent_part.strip(), "entities": parsed_entities}
            )
        return out or [{"index": 1, "sentence": (text or "").strip(), "entities": safe_ents[:2]}]

    async def async_decompose(self, text: str, entities: list[str] | None = None) -> list[dict]:
        return await asyncio.to_thread(self.decompose, text, entities)
