# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""Learn: the verifier fitting its claim spotter to this hub's own rooms.

The hub ships a starting model. Learning replaces it with one fitted to how this
hub's agents actually talk, in three parts:

1. **The hub's model labels past messages, once.** Every agent message in the
   rooms that added the verifier is split into sentences, and the hub's model
   (through Pi) says which sentences claim an approval, a completion, a decision
   or a pull request's state. Batches stay small (:data:`BATCH`): a model asked
   about a few hundred messages at once starts tagging whole messages instead of
   sentences. The labels are kept beside the hub's data, each tagged with its
   room, so a room that is deleted can be dropped from them.
2. **A local classifier is fitted to them** in seconds, on the hub's CPU: one
   logistic regression per kind over the search embeddings, with its threshold
   chosen on messages held back from fitting.
3. **The engine switches to it.** A model change later costs no labeling: the
   labels are re-embedded and the classifier refitted.

*It's fine* answers are kept the same way (:func:`record_answer`).

Plain numpy, no scikit-learn: the Mac app's hub is built without it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.services import embedding, verifier_claims
from app.services.persister import load_transcript

logger = logging.getLogger(__name__)

BATCH = 80
HELD_BACK = 0.15
SEED = 1288
#: What one labeling token costs, roughly, at a small model's price: the
#: estimate is for a person deciding whether to start, not for billing.
USD_PER_TOKEN = 1.5e-6
_LABEL_PROMPT = """You tag claims, sentence by sentence, in messages AI agents posted in a team chat about software work.

Tag a sentence with each of these that it states as already true, whether or not it's true:
- approval: someone approved, signed off on, or agreed to merge or ship something. A reviewer approving something itself counts.
- completion: a piece of work is done, fixed, tested, verified, merged, released, deployed or green.
- decision: a question is settled ("we'll go with X", "keeping the old flag"). Rare.
- pr_state: the current state of a specific pull request, branch, release or task (merged, open, in review, stacked on another, its head moved, held, blocked).

Don't tag questions, plans, offers or requests ("shall I…", "I'll…", "will rebase", "please…"). Don't tag descriptions of how code behaves, opinions or explanations.

Each message below is split into numbered sentences. Answer with one JSON object per message and nothing else:
{{"m": <message number>, "claims": [{{"s": <sentence number>, "kinds": ["approval", ...]}}]}}
Use "claims": [] when a message makes no claim.

{messages}"""


def _dir() -> Path:
    path = Path(settings.MYCELIUM_DATA_DIR) / "verifier"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append(name: str, rows: list[dict[str, Any]]) -> None:
    with (_dir() / name).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read(name: str) -> list[dict[str, Any]]:
    path = _dir() / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def record_answer(room: str, flag: dict[str, Any]) -> None:
    """Keep an *It's fine* answer, tagged with its room."""
    _append(
        "answers.jsonl",
        [
            {
                "room": room,
                "flag_id": flag["flag_id"],
                "message_id": flag["message_id"],
                "claim": flag["claim"],
                "sentence": flag["sentence"],
                "by": flag.get("fine_by"),
                "at": datetime.now(UTC).isoformat(),
            }
        ],
    )


def answers_since(model_at: str | None) -> int:
    return sum(1 for a in _read("answers.jsonl") if model_at is None or a["at"] > model_at)


# ── What there is to learn from ──────────────────────────────────────────────


def agent_messages(rooms: list[str]) -> list[dict[str, Any]]:
    """Agent messages in ``rooms``, with their sentences."""
    from app.services.verifier import PROSE_TYPES, _is_agent

    out = []
    for room in rooms:
        for r in load_transcript(room):
            payload = (r.content.get("l9") or {}).get("payload") or {}
            text = str(r.content.get("content") or "")
            if (
                payload.get("type") not in PROSE_TYPES
                or not text.strip()
                or not _is_agent(room, r.sender)
            ):
                continue
            sentences = verifier_claims.split_sentences(text)
            if sentences:
                out.append({"room": room, "message_id": r.message_id, "sentences": sentences})
    return out


def estimate(rooms: list[str]) -> dict[str, Any]:
    """How much labeling the rooms would take, for the person deciding to start."""
    messages = agent_messages(rooms)
    labeled = {r["message_id"] for r in _read("labels.jsonl")}
    todo = [m for m in messages if m["message_id"] not in labeled]
    chars = sum(len(s) for m in todo for s in m["sentences"])
    batches = -(-len(todo) // BATCH) if todo else 0
    tokens = int(chars / 4 * 1.15) + batches * 700 + len(todo) * 40
    return {
        "messages": len(todo),
        "approx_tokens": tokens,
        "approx_usd": round(tokens * USD_PER_TOKEN, 2),
    }


# ── Labeling ─────────────────────────────────────────────────────────────────


def _ask_model(prompt: str) -> str:
    """One blocking Pi turn on a throwaway session. Isolated so tests patch it."""
    from app.services.pi_session import PiSession

    session_dir = Path(tempfile.gettempdir()) / "mycelium-pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session = PiSession(
        session_path=session_dir / f"verifier-learn-{uuid.uuid4().hex}.jsonl",
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        binary=settings.ALIGNER_PI_BINARY,
        timeout_s=max(settings.VERIFIER_PI_TIMEOUT_S, 300.0),
        openshell=settings.ALIGNER_PI_OPENSHELL,
        operation="verifier_learn",
        room="",
    )
    return session(prompt)


def _parse(answer: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sentence labels from the model's answer, for the messages it answered."""
    labels = []
    answered = set()
    for line in answer.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            x = json.loads(line)
        except ValueError:
            continue
        m = x.get("m")
        if not isinstance(m, int) or not 1 <= m <= len(batch) or m in answered:
            continue
        answered.add(m)
        message = batch[m - 1]
        tagged: dict[int, set[str]] = {}
        for c in x.get("claims") or []:
            s = c.get("s")
            kinds = {k for k in c.get("kinds") or [] if k in verifier_claims.KINDS}
            if isinstance(s, int) and 1 <= s <= len(message["sentences"]) and kinds:
                tagged.setdefault(s, set()).update(kinds)
        for s, sentence in enumerate(message["sentences"], 1):
            labels.append(
                {
                    "room": message["room"],
                    "message_id": message["message_id"],
                    "s": s,
                    "sentence": sentence,
                    "kinds": sorted(tagged.get(s, set())),
                }
            )
    return labels


@dataclass
class Learning:
    """Where a Learn run stands, for the settings page."""

    state: str = "idle"  # idle, running, done, failed
    done: int = 0
    total: int = 0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    rooms: list[str] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        return {"state": self.state, "done": self.done, "total": self.total, "error": self.error}


async def label(rooms: list[str], progress: Learning) -> None:
    """Have the hub's model label every not-yet-labeled agent message in ``rooms``."""
    labeled = {r["message_id"] for r in _read("labels.jsonl")}
    todo = [
        m for m in await asyncio.to_thread(agent_messages, rooms) if m["message_id"] not in labeled
    ]
    progress.total = len(todo)
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        body = "\n\n".join(
            f"--- message {i} ---\n"
            + "\n".join(f"[{s}] {t}" for s, t in enumerate(m["sentences"], 1))
            for i, m in enumerate(batch, 1)
        )
        answer = await asyncio.to_thread(_ask_model, _LABEL_PROMPT.format(messages=body))
        labels = _parse(answer, batch)
        await asyncio.to_thread(_append, "labels.jsonl", labels)
        progress.done = min(progress.total, start + len(batch))


# ── Fitting ──────────────────────────────────────────────────────────────────


def _fit(
    x: np.ndarray, y: np.ndarray, *, steps: int = 400, lr: float = 0.5, l2: float = 1e-3
) -> tuple[np.ndarray, float]:
    """Logistic regression with balanced classes, by plain gradient descent."""
    pos = max(1, int(y.sum()))
    neg = max(1, len(y) - pos)
    weight = np.where(y, len(y) / (2 * pos), len(y) / (2 * neg))
    w = np.zeros(x.shape[1], dtype=np.float64)
    b = 0.0
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-(x @ w + b)))
        g = weight * (p - y)
        w -= lr * (x.T @ g / len(y) + l2 * w)
        b -= lr * float(g.mean())
    return w, b


def _f1(y: np.ndarray, p: np.ndarray) -> float:
    tp = float((y & p).sum())
    fp = float((~y & p).sum())
    fn = float((y & ~p).sum())
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def train(labels: list[dict[str, Any]] | None = None) -> verifier_claims.ClaimModel | None:
    """Fit a claim model to the stored labels and keep it beside the hub's data."""
    labels = labels if labels is not None else _read("labels.jsonl")
    if not labels:
        return None
    sentences = [r["sentence"] for r in labels]
    x = np.asarray(embedding.embed_texts(sentences), dtype=np.float64)
    messages = sorted({r["message_id"] for r in labels})
    rng = random.Random(SEED)
    held = {m for m in messages if rng.random() < HELD_BACK}
    is_held = np.array([r["message_id"] in held for r in labels])
    owner = {m: i for i, m in enumerate(messages)}
    msg_of = np.array([owner[r["message_id"]] for r in labels])

    weights, intercepts, thresholds = {}, {}, {}
    for kind in verifier_claims.KINDS:
        y = np.array([kind in r["kinds"] for r in labels])
        if y[~is_held].sum() == 0:
            continue
        w, b = _fit(x[~is_held], y[~is_held])
        prob = 1.0 / (1.0 + np.exp(-(x @ w + b)))
        msg_y = np.zeros(len(messages), dtype=bool)
        msg_p = np.zeros(len(messages))
        np.logical_or.at(msg_y, msg_of, y)
        np.maximum.at(msg_p, msg_of, prob)
        held_msgs = np.array([m in held for m in messages])
        threshold = max(
            np.arange(0.5, 0.99, 0.02),
            key=lambda t: _f1(msg_y[held_msgs], msg_p[held_msgs] >= t),
        )
        w, b = _fit(x, y)
        weights[kind] = w.astype(np.float32)
        intercepts[kind] = b
        thresholds[kind] = float(threshold)
    if not weights:
        return None
    model = verifier_claims.ClaimModel(
        embedding_model=embedding.model_name(),
        weights=weights,
        intercepts=intercepts,
        thresholds=thresholds,
        source="learned",
        trained_on={"messages": len(messages), "sentences": len(labels)},
    )
    path = verifier_claims.learned_path(Path(settings.MYCELIUM_DATA_DIR), model.embedding_model)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model.to_json()
    data["trained_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return model


def drop_room(room: str) -> None:
    """Forget what was learned from a room: its labels and answers."""
    for name in ("labels.jsonl", "answers.jsonl"):
        rows = [r for r in _read(name) if r.get("room") != room]
        path = _dir() / name
        if path.exists():
            path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
            )


def labeled_rooms() -> list[str]:
    return sorted({r["room"] for r in _read("labels.jsonl")})
