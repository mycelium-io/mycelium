# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9 episode tracking for CFN negotiations.

One :class:`EpisodeState` accompanies each ``_CfnRoundState`` in
``coordination.py``. It does three things:

1. Builds the L9 envelopes that ride inside coordination message content
   (ticks are ``exchange``, the consensus is ``commit:converged`` /
   ``commit:abort``) and threads causality: a tick's envelope parents the
   agent's prior reply, a reply parents the tick it answers, the consensus
   parents the final round's replies. Agents don't speak L9 themselves:
   the backend synthesizes reply envelopes from the parsed reply dicts, so
   the causal graph is complete without requiring L9-aware agents.

2. Tracks the epistemic fields agents volunteer (``confidence``,
   ``deferred_to``) and computes the SIEP-style agreement-quality metrics
   at consensus: MPC (mean final confidence), GAR (genuine agreement
   ratio: whose confidence moved toward the outcome relative to their
   first stated confidence), SCR (social compliance ratio: accepts made
   by deference), and provenance_weight = (1 - SCR) * GAR. Interim: these
   move to the Cognition Engine when it computes them natively.

3. Writes the full episode record to the parent room's memory under
   ``log/episodes/{short_id}.md`` at close: git-shareable and indexed by
   the normal memory path.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services import l9
from app.services.l9_models import Kind

logger = logging.getLogger(__name__)

# Cap the evidence list / reasoning length accepted from a single reply so a
# misbehaving agent can't balloon episode records.
MAX_EVIDENCE_ITEMS = 20
MAX_REASONING_CHARS = 2000

# SIEP belief.revision_cause vocabulary. Only ``social_compliance`` drives SCR;
# the rest count as genuine revisions.
_VALID_REVISION_CAUSES = frozenset(
    {
        "grounded_argument",
        "social_compliance",
        "new_evidence",
        "semantic_memory",
        "repair_resolution",
    }
)
# A turn is grounded when its ``addresses`` overlap prior evidence by at least
# this fraction (spec contingency_score threshold θ_c).
_GROUNDING_THRESHOLD = 0.40
# A posterior shift larger than this counts as a genuine belief move.
_MOVE_EPS = 0.05


def _clean_str_list(value: Any) -> list[str]:
    """Non-empty trimmed strings from a reply list field, capped. [] otherwise."""
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()][:MAX_EVIDENCE_ITEMS]


@dataclass
class EpisodeState:
    """L9 episode accumulator for one coordination session."""

    episode: str  # URN
    topic: str  # concept URN
    parent_room: str
    short_id: str
    workspace_id: str
    mas_id: str
    agents: list[str]
    intent_id: str = ""
    # Ordered record of every envelope in the episode (dicts, wire shape).
    messages: list[dict[str, Any]] = field(default_factory=list)
    # handle -> l9 message id of the last tick sent to that agent.
    last_tick_ids: dict[str, str] = field(default_factory=dict)
    # handle -> l9 message id of that agent's last recorded reply.
    last_reply_ids: dict[str, str] = field(default_factory=dict)
    # handle -> first confidence the agent stated (its prior).
    priors: dict[str, float] = field(default_factory=dict)
    # handle -> most recent confidence stated.
    last_confidence: dict[str, float] = field(default_factory=dict)
    # handle -> deferred_to handle on the agent's most recent accept, if any.
    deferred: dict[str, str] = field(default_factory=dict)
    # Union of all supporting-evidence keys stated so far: the grounding pool a
    # later turn's ``addresses`` is scored against (contingency_score).
    evidence_pool: set[str] = field(default_factory=set)
    # handle -> final revision_cause (explicit or derived). Feeds genuine SCR.
    revision_cause: dict[str, str] = field(default_factory=dict)


def open_episode(
    *,
    parent_room: str,
    short_id: str,
    workspace_id: str,
    mas_id: str,
    agents: list[str],
    joined_intents: str,
) -> EpisodeState:
    """Open the episode: mint URNs and record the ``intent`` envelope."""
    ep = EpisodeState(
        episode=l9.episode_urn(parent_room, short_id),
        topic=l9.topic_urn(parent_room),
        parent_room=parent_room,
        short_id=short_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agents=agents[:],
    )
    intent = l9.build_envelope(
        kind=Kind.intent,
        subkind="mission",
        episode=ep.episode,
        recipients=agents,
        topic=ep.topic,
        workspace_id=workspace_id or None,
        mas_id=mas_id or None,
        payload_type="utterance",
        payload_data={"content": joined_intents},
    )
    ep.intent_id = intent.header.message.id  # type: ignore[union-attr]
    ep.messages.append(l9.envelope_to_dict(intent))
    return ep


def record_tick(
    ep: EpisodeState, *, handle: str, round_n: int | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record the tick sent to ``handle`` and return its envelope dict.

    The returned dict is what ``_fan_out_cfn_messages`` embeds as the tick
    content's ``l9`` key. Parents: the agent's prior reply if any, else the
    episode intent.
    """
    parent = ep.last_reply_ids.get(handle) or ep.intent_id
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=ep.episode,
        parents=[parent] if parent else [],
        recipients=[handle],
        topic=ep.topic,
        payload_type="tick",
        payload_data={
            "round": round_n,
            "action": payload.get("action"),
            "current_offer": payload.get("current_offer"),
        },
    )
    env_dict = l9.envelope_to_dict(env)
    ep.last_tick_ids[handle] = env.header.message.id  # type: ignore[union-attr]
    ep.messages.append(env_dict)
    return env_dict


def record_reply(
    ep: EpisodeState,
    *,
    handle: str,
    reply: dict[str, Any],
    round_n: int | None,
    synthesised: bool = False,
) -> None:
    """Record an agent's parsed reply as a synthesized ``exchange`` envelope.

    Called once per agent per round at decide time (so resubmits collapse to
    the reply that actually counted). Also folds the epistemic fields into the
    prior/posterior/deference tracking used by the consensus metrics.
    """
    action = str(reply.get("action") or "reject")
    payload_data: dict[str, Any] = {"round": round_n, "action": action}
    if synthesised:
        payload_data["synthesised"] = True
    if isinstance(reply.get("offer"), dict):
        payload_data["offer"] = reply["offer"]
    for k in (
        "confidence",
        "evidence",
        "supporting_evidence",
        "against_evidence",
        "addresses",
        "revision_cause",
        "deferred_to",
        "reasoning",
    ):
        if reply.get(k) is not None:
            payload_data[k] = reply[k]

    parent = ep.last_tick_ids.get(handle) or ep.intent_id
    env = l9.build_envelope(
        kind=Kind.exchange,
        episode=ep.episode,
        parents=[parent] if parent else [],
        sender=handle,
        sender_role="agent",
        recipients=[l9.SYSTEM_ACTOR_ID],
        topic=ep.topic,
        payload_type="reply",
        payload_data=payload_data,
    )
    ep.last_reply_ids[handle] = env.header.message.id  # type: ignore[union-attr]
    ep.messages.append(l9.envelope_to_dict(env))

    # --- epistemic folding: belief move, grounding, revision cause ---
    conf = reply.get("confidence")
    prior = ep.priors.get(handle)  # None until the agent first states confidence
    new_conf: float | None = None
    if isinstance(conf, int | float) and not isinstance(conf, bool) and 0.0 <= conf <= 1.0:
        new_conf = float(conf)

    # Grounding: does this turn engage prior evidence? Score BEFORE folding this
    # turn's own evidence into the pool, so a turn can't ground itself.
    addresses = set(_clean_str_list(reply.get("addresses")))
    grounded: bool | None = None
    if addresses:
        contingency = len(addresses & ep.evidence_pool) / len(addresses)
        grounded = contingency >= _GROUNDING_THRESHOLD

    deferred_to = reply.get("deferred_to")
    is_defer = action == "accept" and isinstance(deferred_to, str) and bool(deferred_to.strip())

    # Revision cause: an explicit, valid self-report wins; otherwise derive it
    # from whether the belief moved and whether the move was grounded.
    cause = reply.get("revision_cause")
    if not (isinstance(cause, str) and cause in _VALID_REVISION_CAUSES):
        cause = None
    if cause is None:
        moved = prior is not None and new_conf is not None and abs(new_conf - prior) > _MOVE_EPS
        if is_defer:
            cause = "social_compliance"
        elif moved:
            # Weak grounding (``addresses`` given but overlap below threshold) is
            # the only *derived* compliance signal. Movement with no addresses at
            # all gets the benefit of the doubt -- an agent that doesn't use the
            # optional grounding flags must not be scored as complying.
            cause = "social_compliance" if grounded is False else "grounded_argument"
    if cause is not None:
        ep.revision_cause[handle] = cause

    # Fold this turn's supporting evidence into the grounding pool for later turns.
    supporting = _clean_str_list(reply.get("supporting_evidence")) or _clean_str_list(
        reply.get("evidence")
    )
    ep.evidence_pool.update(supporting)

    # Prior = first stated confidence (immutable); last_confidence = latest.
    if new_conf is not None:
        ep.priors.setdefault(handle, new_conf)
        ep.last_confidence[handle] = new_conf

    # Keep deference for the episode record; SCR now derives from revision_cause.
    if action == "accept":
        if isinstance(deferred_to, str) and deferred_to.strip():
            ep.deferred[handle] = deferred_to.strip()
        else:
            ep.deferred.pop(handle, None)


def compute_metrics(ep: EpisodeState) -> dict[str, Any] | None:
    """SIEP agreement-quality metrics over the agents that reported confidence.
    Returns None when participation is too thin to mean anything (fewer than two
    reporters, or more than one silent agent)."""
    conf = ep.last_confidence
    if len(conf) < 2 or len(conf) < len(ep.agents) - 1:
        return None

    mpc = sum(conf.values()) / len(conf)
    # GAR: fraction whose posterior moved toward the outcome relative to prior.
    # At mpc == 0.5 the direction term vanishes (a spec degeneracy that would
    # otherwise score maximal disagreement as unanimity), so credit only agents
    # that did not move -- they at least weren't coerced.
    direction = mpc - 0.5
    genuine = 0
    for h, c in conf.items():
        delta = c - ep.priors.get(h, c)
        if abs(direction) < 1e-9:
            if abs(delta) < 1e-9:
                genuine += 1
        elif delta * direction >= 0:
            genuine += 1
    gar = genuine / len(conf)
    # SCR: fraction of belief revisions caused by social compliance rather than
    # grounded argument, over the agents that actually revised (spec definition).
    revisers = list(ep.revision_cause)
    scr = (
        sum(1 for h in revisers if ep.revision_cause[h] == "social_compliance") / len(revisers)
        if revisers
        else 0.0
    )
    return {
        "mpc": round(mpc, 4),
        "gar": round(gar, 4),
        "scr": round(scr, 4),
        "provenance_weight": round((1.0 - scr) * gar, 4),
        "participants": len(conf),
    }


def build_consensus_envelope(
    ep: EpisodeState,
    *,
    broken: bool,
    assignments: dict[str, Any],
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """The ``commit`` envelope closing the episode (converged or abort)."""
    parents = sorted(ep.last_reply_ids.values()) or ([ep.intent_id] if ep.intent_id else [])
    payload: dict[str, Any] = {"assignments": assignments}
    if metrics:
        payload["metrics"] = metrics
    env = l9.build_envelope(
        kind=Kind.commit,
        subkind="abort" if broken else "converged",
        episode=ep.episode,
        parents=parents,
        recipients=ep.agents,
        topic=ep.topic,
        workspace_id=ep.workspace_id or None,
        mas_id=ep.mas_id or None,
        payload_type="consensus",
        payload_data=payload,
    )
    env_dict = l9.envelope_to_dict(env)
    ep.messages.append(env_dict)
    return env_dict


def write_episode_record(
    ep: EpisodeState,
    *,
    outcome: str,
    metrics: dict[str, Any] | None,
    plan_file: str | None,
) -> None:
    """Persist the episode to ``log/episodes/{short_id}.md`` in the parent
    room's memory. Best-effort: never raises into the consensus path."""
    try:
        from app.services.filesystem import get_room_dir, write_memory_file

        lines = [
            f"# Episode {ep.episode}",
            "",
            f"- topic: `{ep.topic}`",
            f"- outcome: **{outcome}**",
            f"- participants: {', '.join(ep.agents)}",
        ]
        if metrics:
            lines.append(
                f"- quality: MPC {metrics['mpc']:.2f} · GAR {metrics['gar']:.2f} · "
                f"SCR {metrics['scr']:.2f} · provenance weight "
                f"{metrics['provenance_weight']:.2f}"
            )
        if plan_file:
            lines.append(f"- plan: `{plan_file}`")
        lines += [
            "",
            "## Messages",
            "",
            "The full causally-linked L9 message record (one JSON envelope per line):",
            "",
            "```jsonl",
            *(json.dumps(m, sort_keys=True) for m in ep.messages),
            "```",
            "",
        ]
        base = get_room_dir(ep.parent_room)
        base.mkdir(parents=True, exist_ok=True)
        write_memory_file(
            base,
            f"log/episodes/{ep.short_id}",
            "\n".join(lines),
            created_by=l9.SYSTEM_ACTOR_ID,
            updated_by=l9.SYSTEM_ACTOR_ID,
        )
    except Exception:
        logger.exception("episode record write failed for %s", ep.episode)


# One canonical converged-rule memory per room (each room is one topic). Reading
# it back on the next episode is the mycelium-local team_prior loop; it does not
# touch the CFN knowledge store (that path is l9_cfn, off by default).
_RULE_UPDATE_KEY = "l9/rule_update/topic"


def write_rule_update(ep: EpisodeState, metrics: dict[str, Any]) -> None:
    """Persist the converged rule to the parent room's memory so a later episode
    on this topic can read its provenance-weighted prior back. Best-effort."""
    try:
        from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file

        base = get_room_dir(ep.parent_room)
        # Count how many times this topic has converged (for prior weighting).
        episode_count = 1
        existing = read_memory_file(base, _RULE_UPDATE_KEY)
        if existing:
            prev = existing[0].get("l9")
            if isinstance(prev, dict):
                try:
                    episode_count = int(prev.get("episode_count", 0)) + 1
                except (TypeError, ValueError):
                    episode_count = 1
        rule = {
            "posterior": metrics["mpc"],
            "gar": metrics["gar"],
            "scr": metrics["scr"],
            "provenance_weight": metrics["provenance_weight"],
            "revision_cause": "converged_episode",
            "episode_id": ep.episode,
            "episode_count": episode_count,
        }
        content = (
            f"Converged rule for `{ep.topic}`: posterior {metrics['mpc']:.2f}, "
            f"provenance_weight {metrics['provenance_weight']:.2f} "
            f"(episode {ep.short_id}, {episode_count} converged)."
        )
        base.mkdir(parents=True, exist_ok=True)
        write_memory_file(
            base,
            _RULE_UPDATE_KEY,
            content,
            created_by=l9.SYSTEM_ACTOR_ID,
            updated_by=l9.SYSTEM_ACTOR_ID,
            extra_meta={"l9": rule},
        )
    except Exception:
        logger.exception("rule_update write failed for %s", ep.episode)


def read_team_prior_local(parent_room: str) -> dict[str, Any] | None:
    """Read the last converged rule for this room back as a tick-ready
    ``team_prior`` dict. None when no prior episode has converged."""
    try:
        from app.services.filesystem import get_room_dir, read_memory_file

        result = read_memory_file(get_room_dir(parent_room), _RULE_UPDATE_KEY)
        if not result:
            return None
        rule = result[0].get("l9")
        if not isinstance(rule, dict):
            return None
        posterior = rule.get("posterior")
        pw = rule.get("provenance_weight")
        if not isinstance(posterior, int | float) or not isinstance(pw, int | float):
            return None
        try:
            episode_count = int(rule.get("episode_count", 1))
        except (TypeError, ValueError):
            episode_count = 1
        return {
            "confidence": float(posterior),
            "provenance_weight": float(pw),
            "episode_count": episode_count,
            "source": "mycelium-memory",
        }
    except Exception:
        logger.exception("local team-prior read failed for %s", parent_room)
        return None


def sanitize_epistemic_fields(parsed: dict[str, Any], result: dict[str, Any]) -> None:
    """Copy validated epistemic fields from a raw agent reply into the parsed
    reply dict. Invalid values are dropped, never rejected: epistemic fields
    must not break a legacy-shaped negotiation."""
    conf = parsed.get("confidence")
    if isinstance(conf, int | float) and not isinstance(conf, bool) and 0.0 <= conf <= 1.0:
        result["confidence"] = float(conf)
    for key in ("evidence", "supporting_evidence", "against_evidence", "addresses"):
        cleaned = _clean_str_list(parsed.get(key))
        if cleaned:
            result[key] = cleaned
    cause = parsed.get("revision_cause")
    if isinstance(cause, str) and cause in _VALID_REVISION_CAUSES:
        result["revision_cause"] = cause
    deferred_to = parsed.get("deferred_to")
    if isinstance(deferred_to, str) and deferred_to.strip() and result.get("action") == "accept":
        result["deferred_to"] = deferred_to.strip()
    reasoning = parsed.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        result["reasoning"] = reasoning.strip()[:MAX_REASONING_CHARS]
