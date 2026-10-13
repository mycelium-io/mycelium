# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Spotting claims in a message: the verifier's first, local step.

A message is split into sentences, each sentence is embedded with the hub's
search model, and a small linear classifier per claim kind says whether the
sentence makes that kind of claim: an approval, a completion, a decision, or the
state of a pull request. It runs on every agent message in a room that added the
verifier, so it has to be cheap: one embedding call and a dot product per kind.

The classifier's weights are tied to the embedding model they were trained on.
The hub ships a starting model per supported embedding model
(``app/data/verifier/<model>.json``); a hub that has learned from its own rooms
keeps its own beside its data (``<data dir>/verifier/model-<model>.json``) and
prefers it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.services import embedding

logger = logging.getLogger(__name__)

KINDS = ("approval", "completion", "decision", "pr_state")
SHIPPED_DIR = Path(__file__).resolve().parent.parent / "data" / "verifier"
MAX_SENTENCES = 40
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    """Sentences and list items, the units a claim is usually made in."""
    parts = [p.strip(" -*•\t") for p in _SENTENCE_END.split(text)]
    return [p for p in parts if len(p) > 3][:MAX_SENTENCES]


def _file_name(model: str) -> str:
    return model.rsplit("/", 1)[-1] + ".json"


def learned_path(data_dir: Path, model: str) -> Path:
    return data_dir / "verifier" / f"model-{_file_name(model)}"


@dataclass
class ClaimModel:
    """One linear classifier per claim kind, over one embedding model's vectors."""

    embedding_model: str
    weights: dict[str, np.ndarray]
    intercepts: dict[str, float]
    thresholds: dict[str, float]
    source: str  # "starting" or "learned"
    trained_on: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any], source: str) -> ClaimModel:
        kinds = data["kinds"]
        return cls(
            embedding_model=data["embedding_model"],
            weights={k: np.asarray(v["coef"], dtype=np.float32) for k, v in kinds.items()},
            intercepts={k: float(v["intercept"]) for k, v in kinds.items()},
            thresholds={k: float(v["threshold"]) for k, v in kinds.items()},
            source=source,
            trained_on=dict(data.get("trained_on") or {}),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "embedding_model": self.embedding_model,
            "dimensions": int(next(iter(self.weights.values())).shape[0]),
            "trained_on": self.trained_on,
            "kinds": {
                k: {
                    "coef": [round(float(x), 6) for x in self.weights[k]],
                    "intercept": round(self.intercepts[k], 6),
                    "threshold": round(self.thresholds[k], 2),
                }
                for k in self.weights
            },
        }

    def probabilities(self, vectors: np.ndarray) -> dict[str, np.ndarray]:
        """Each kind's probability for each row of ``vectors``."""
        return {
            k: 1.0 / (1.0 + np.exp(-(vectors @ w + self.intercepts[k])))
            for k, w in self.weights.items()
        }


def load(data_dir: Path) -> ClaimModel | None:
    """This hub's learned model if it has one, else the shipped starting model.

    ``None`` when neither exists for the embedding model in use: an embedding
    model the hub didn't ship a starting model for, and that hasn't been learned on.
    """
    model = embedding.model_name()
    for path, source in (
        (learned_path(data_dir, model), "learned"),
        (SHIPPED_DIR / _file_name(model), "starting"),
    ):
        if path.exists():
            try:
                loaded = ClaimModel.from_json(json.loads(path.read_text(encoding="utf-8")), source)
            except (OSError, ValueError, KeyError):
                logger.exception("verifier: unreadable claim model %s", path)
                continue
            if loaded.embedding_model == model:
                return loaded
    return None


@dataclass
class Claim:
    """A sentence the classifier thinks makes a claim, and of which kinds."""

    index: int
    sentence: str
    kinds: frozenset[str]


def spot(model: ClaimModel, text: str) -> list[Claim]:
    """The sentences of ``text`` that make a claim, by kind."""
    sentences = split_sentences(text)
    if not sentences:
        return []
    vectors = np.asarray(embedding.embed_texts(sentences), dtype=np.float32)
    probs = model.probabilities(vectors)
    claims = []
    for i, sentence in enumerate(sentences):
        kinds = frozenset(k for k, p in probs.items() if p[i] >= model.thresholds[k])
        if kinds:
            claims.append(Claim(i, sentence, kinds))
    return claims
