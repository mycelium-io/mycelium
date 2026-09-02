# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
L9 episode tracking.

:class:`EpisodeState` is what any episode is — a tagged thread over the room's
channel, with its participants, its topic and the envelopes it has carried.
:class:`NegotiationState` adds what a *negotiation* inside one accumulates: the
opening asks, the offer grid, and the belief-move scoreboard. The split is the
task model's: a task is a thread, and a negotiation is one optional
thing that happens inside it, so a thread opened for a board row does
not carry an SAO scoreboard it will never fill in.

A :class:`NegotiationState` accompanies each mediated session. It does three
things:

1. Builds the L9 envelopes that ride inside coordination message content
   (ticks are ``exchange``, the consensus is ``commit:converged`` /
   ``commit:rejected``) and threads causality: a tick's envelope parents the
   agent's prior reply, a reply parents the tick it answers, the consensus
   parents the final round's replies. Agents don't speak L9 themselves:
   the backend synthesizes reply envelopes from the parsed reply dicts, so
   the causal graph is complete without requiring L9-aware agents.

2. Tracks the epistemic fields agents volunteer (``confidence``,
   ``deferred_to``) and computes the SIEP-style agreement-quality metrics
   at consensus: MPC (mean final confidence), GAR (genuine agreement
   ratio: whose confidence moved toward the outcome relative to their
   first stated confidence), SCR (social compliance ratio: accepts made
   by deference), and provenance_weight = (1 - SCR) * GAR.

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
    """What every episode is: a tagged thread over the room's own channel.

    A task is one of these; so is a negotiation inside a task. Everything
    here is what a thread has whatever happens in it — who it is scoped to, what
    it is about, and the envelopes it has carried. The accumulators a *negotiation*
    needs are :class:`NegotiationState`'s, so opening a thread for a board row
    does not drag an SAO scoreboard along with it.
    """

    episode: str  # URN
    topic: str  # concept URN
    parent_room: str
    short_id: str
    workspace_id: str
    mas_id: str
    agents: list[str]
    # The registered engine mediating this episode (e.g. "aligner"). Signs the
    # engine-authored envelopes — intent, ticks, consensus — so the wire carries
    # the engine's real identity, not the generic system actor. Empty → falls
    # back to the system actor (an episode opened outside an engine context).
    engine_handle: str = ""
    intent_id: str = ""
    # Ordered record of every envelope in the episode (dicts, wire shape).
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NegotiationState(EpisodeState):
    """The extra bookkeeping a *negotiation* inside an episode accumulates.

    Split from :class:`EpisodeState` because a negotiation is one optional thing
    that can happen inside a task rather than the reason the task exists.
    Opening positions, an SAO offer grid and the belief-move scoreboard mean
    nothing to a thread nobody is negotiating in.
    """

    # Each participant's opening prose, captured before mediation runs — the
    # structured snapshot the episode record renders as "Opening Positions" so a
    # negotiation can be audited against what the room believed going in.
    opening_positions: dict[str, str] = field(default_factory=dict)
    # Terms the pre-negotiation check found the participants using in different
    # senses, and what each answered in the clarifying round that followed. Empty
    # on the common path (no mismatch, no clarifying round).
    term_mismatches: list[dict[str, Any]] = field(default_factory=list)
    clarifications: dict[str, str] = field(default_factory=dict)
    # Each agent's first concrete SAO offer (issue -> value), captured as the
    # mediator reads it — the "opening ask" a converged outcome's satisfaction is
    # scored against. Distinct from opening_positions (prose): parsed offers.
    opening_offers: dict[str, dict[str, str]] = field(default_factory=dict)
    # The negotiable issues' ordered option grids (issue -> options), so
    # satisfaction can be scored as ordinal distance on the grid actually negotiated.
    issue_options: dict[str, list[str]] = field(default_factory=dict)
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
    engine_handle: str = "",
    opening_positions: dict[str, str] | None = None,
) -> NegotiationState:
    """Open a negotiation episode: mint URNs and record the ``intent`` envelope.

    ``engine_handle`` is the registered engine mediating the episode; it signs
    the intent/tick/consensus envelopes so the wire carries the engine's real
    identity. Empty falls back to the system actor.

    ``opening_positions`` is each participant's stated prose at the start,
    captured before mediation runs; it is rendered into the episode record's
    "Opening Positions" section for audit.
    """
    ep = NegotiationState(
        episode=l9.episode_urn(parent_room, short_id),
        topic=l9.topic_urn(parent_room),
        parent_room=parent_room,
        short_id=short_id,
        workspace_id=workspace_id,
        mas_id=mas_id,
        agents=agents[:],
        engine_handle=engine_handle,
        opening_positions=dict(opening_positions or {}),
    )
    intent = l9.build_envelope(
        kind=Kind.intent,
        subkind="mission",
        episode=ep.episode,
        sender=engine_handle or l9.SYSTEM_ACTOR_ID,
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
    ep: NegotiationState, *, handle: str, round_n: int | None, payload: dict[str, Any]
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
        sender=ep.engine_handle or l9.SYSTEM_ACTOR_ID,
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


def record_term_check(
    ep: NegotiationState,
    *,
    mismatches: list[dict[str, Any]],
    clarifications: dict[str, str],
) -> None:
    """Record the pre-negotiation term check and the clarifying round it drove.

    Kept off the quality metrics on purpose: the clarifying round is vocabulary
    repair, not a negotiation move, so folding it into MPC/GAR/SCR would score a
    definition as a concession. It lands in the episode record instead, where an
    audit can see which words the room had to agree on before it could agree.
    """
    ep.term_mismatches = [dict(m) for m in mismatches]
    ep.clarifications = {h: t for h, t in clarifications.items() if t.strip()}


def record_reply(
    ep: NegotiationState,
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
    # The wire move type (l9.EXCHANGE_MOVE_SUBKINDS) is distinct from ``action``:
    # ``action`` keeps its accept/hold semantics for the belief-move metrics
    # below, while ``move`` records what the agent actually did (a proposer's
    # offer folds to action=accept for the metrics but is a ``counter`` on the
    # wire). Absent or unrecognized -> no subkind, so the reply stays valid.
    move = reply.get("move")
    subkind = move if move in l9.EXCHANGE_MOVE_SUBKINDS else None
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
        subkind=subkind,
        episode=ep.episode,
        parents=[parent] if parent else [],
        sender=handle,
        sender_role="agent",
        recipients=[ep.engine_handle or l9.SYSTEM_ACTOR_ID],
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


def compute_metrics(ep: NegotiationState) -> dict[str, Any] | None:
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


def estimate_satisfaction(
    opening_offers: dict[str, dict[str, str]],
    assignments: dict[str, Any],
    issue_options: dict[str, list[str]],
) -> dict[str, float]:
    """Estimate each agent's satisfaction with the agreed outcome, relative to its
    own opening offer, as mean closeness across the issues it stated.

    Closeness on an issue is ``1 - grid_distance / grid_span``, treating each
    issue's option list as ordinal — the order ``discover_issues`` emits (ascending
    numbers, low->high scope). An agent that got exactly its opening ask scores
    ``1.0``; the further the agreed value sits from it on the grid, the lower. It's
    a post-hoc estimate, not a utility the agent stated: agents with no recorded
    offer, and issues absent from an offer or the agreement, are skipped rather
    than guessed. The room's minimum flags a consensus that one participant barely
    tolerated.
    """
    out: dict[str, float] = {}
    for handle, offer in opening_offers.items():
        scores: list[float] = []
        for issue, options in issue_options.items():
            want, got = offer.get(issue), assignments.get(issue)
            if want is None or got is None:
                continue
            try:
                distance = abs(options.index(str(want)) - options.index(str(got)))
            except ValueError:
                continue
            scores.append(1.0 - distance / max(1, len(options) - 1))
        if scores:
            out[handle] = round(sum(scores) / len(scores), 4)
    return out


def build_consensus_envelope(
    ep: NegotiationState,
    *,
    broken: bool,
    assignments: dict[str, Any],
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    """The ``commit`` envelope closing the episode (converged or rejected)."""
    parents = sorted(ep.last_reply_ids.values()) or ([ep.intent_id] if ep.intent_id else [])
    payload: dict[str, Any] = {"assignments": assignments}
    if metrics:
        payload["metrics"] = metrics
    env = l9.build_envelope(
        kind=Kind.commit,
        subkind="rejected" if broken else "converged",
        episode=ep.episode,
        parents=parents,
        sender=ep.engine_handle or l9.SYSTEM_ACTOR_ID,
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
    tasks: list[str] | None,
) -> None:
    """Persist the episode to ``log/episodes/{short_id}.md`` in the parent
    room's memory. Best-effort: never raises into the consensus path."""
    try:
        lines = [
            f"# Episode {ep.episode}",
            "",
            f"- topic: `{ep.topic}`",
            f"- outcome: **{outcome}**",
            f"- participants: {', '.join(ep.agents)}",
        ]
        if metrics and "mpc" in metrics:
            lines.append(
                f"- quality: MPC {metrics['mpc']:.2f} · GAR {metrics['gar']:.2f} · "
                f"SCR {metrics['scr']:.2f} · provenance weight "
                f"{metrics['provenance_weight']:.2f}"
            )
        if metrics and metrics.get("min_satisfaction") is not None:
            per_agent = metrics.get("satisfaction", {})
            lines.append(
                f"- satisfaction: min {metrics['min_satisfaction']:.2f} "
                f"(least-happy of {len(per_agent)} agents, relative to opening asks)"
            )
        if tasks:
            lines.append("- work: " + ", ".join(f"`{key}`" for key in tasks))
        # The header and the envelope chain are any thread's; the sections below
        # exist only where a negotiation actually ran.
        if not isinstance(ep, NegotiationState):
            _append_messages(lines, ep)
            _write_record(ep, lines)
            return
        if ep.opening_positions:
            lines += [
                "",
                "## Opening Positions",
                "",
                "Each participant's stated position at the start, before mediation:",
                "",
                *(
                    f"- **@{handle}**: {ep.opening_positions[handle]}"
                    for handle in ep.agents
                    if handle in ep.opening_positions
                ),
            ]
        if ep.term_mismatches:
            lines += [
                "",
                "## Term Clarifications",
                "",
                "Terms the participants were using differently, caught before the first "
                "offer, and what each said they meant:",
                "",
            ]
            for mismatch in ep.term_mismatches:
                lines.append(f"- **{mismatch.get('term', '')}**")
                readings = mismatch.get("readings")
                if isinstance(readings, dict):
                    lines += [f"  - read by @{handle} as: {r}" for handle, r in readings.items()]
            if ep.clarifications:
                lines += [
                    "",
                    "Clarifying round:",
                    "",
                    *(
                        f"- **@{handle}**: {ep.clarifications[handle]}"
                        for handle in ep.agents
                        if handle in ep.clarifications
                    ),
                ]
        _append_messages(lines, ep)
        _write_record(ep, lines)
    except Exception:
        logger.exception("episode record write failed for %s", ep.episode)


def _append_messages(lines: list[str], ep: EpisodeState) -> None:
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


def _write_record(ep: EpisodeState, lines: list[str]) -> None:
    from app.services.filesystem import get_room_dir, write_memory_file
    from app.services.tasks import carry_thread

    base = get_room_dir(ep.parent_room)
    base.mkdir(parents=True, exist_ok=True)
    key = f"log/episodes/{ep.short_id}"
    write_memory_file(
        base,
        key,
        "\n".join(lines),
        created_by=l9.SYSTEM_ACTOR_ID,
        updated_by=l9.SYSTEM_ACTOR_ID,
        # This write skips the upsert that mints one, and a record of a
        # conversation is still a thing to have a conversation about.
        extra_meta=carry_thread(ep.parent_room, key),
    )


# One canonical converged-rule memory per room (each room is one topic). Reading
# it back on the next episode is the mycelium-local team_prior loop; it does not
# touch the CFN knowledge store (that path is l9_cfn, off by default).
_RULE_UPDATE_KEY = "l9/rule_update/topic"


def write_rule_update(ep: EpisodeState, metrics: dict[str, Any]) -> None:
    """Persist the converged rule to the parent room's memory so a later episode
    on this topic can read its provenance-weighted prior back. Best-effort."""
    try:
        from app.services.filesystem import get_room_dir, read_memory_file, write_memory_file
        from app.services.tasks import carry_thread

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
            # Rewritten in place on every convergence, so its binding has to be
            # carried rather than minted: a fresh URN each time would strand the
            # conversation about the rule on the thread it used to have.
            extra_meta={"l9": rule, **carry_thread(ep.parent_room, _RULE_UPDATE_KEY)},
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
