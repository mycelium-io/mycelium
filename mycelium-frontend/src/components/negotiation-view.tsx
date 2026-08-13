// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo } from "react";
import { Scale, X } from "lucide-react";
import { EmptyState } from "@/components/empty-state";

// The Negotiation instrument: the aligner's NEGMAS Stacked Alternating Offers
// mechanism made visible. It reconstructs, purely from the coordination_tick /
// coordination_consensus events already on the wire, the three things that make
// mycelium a negotiation tool and not a group chat:
//   1. the Current Offer board (issues → standing values, updated live),
//   2. the Agent × Round swim lanes (each cell a move glyph), and
//   3. convergence (the board locks, the state flips to consensus).

/** The subset of a parsed stream event this view reads (structurally
 *  compatible with EventStream's Event). */
interface NegEvent {
  type: string;
  sender: string;
  episode: string | null;
  time: string;
  raw: Record<string, unknown>;
}

type MoveAction = "propose" | "counter" | "accept" | "reject" | string;

interface Negotiation {
  episode: string | null;
  issues: string[];
  offer: Record<string, string>;
  agents: string[];
  rounds: number;
  currentRound: number;
  moves: Record<string, MoveAction>; // `${agent}#${round}` -> action
  state: "idle" | "negotiating" | "converged" | "rejected";
  gar?: number;
}

const episodeOf = (e: NegEvent): string | null =>
  e.episode ?? (e.raw.episode as string | undefined) ?? (e.raw.session as string | undefined) ?? null;

const tickPayload = (e: NegEvent): Record<string, unknown> =>
  (e.raw.payload as Record<string, unknown> | undefined) ?? e.raw;

function derive(events: readonly NegEvent[]): Negotiation {
  const ticks = events.filter(e => e.type === "coordination_tick");
  const consensuses = events.filter(e => e.type === "coordination_consensus");
  const joins = events.filter(e => e.type === "coordination_join");

  const empty: Negotiation = {
    episode: null, issues: [], offer: {}, agents: [], rounds: 1, currentRound: 0, moves: {}, state: "idle",
  };
  const last = [...ticks, ...consensuses].at(-1);
  if (!last) return empty;
  const episode = episodeOf(last);

  const epTicks = ticks.filter(t => episodeOf(t) === episode);
  const epCons = consensuses.filter(c => episodeOf(c) === episode);

  // Issues + standing offer: each tick's current_offer overwrites; consensus
  // assignments finalize.
  const offer: Record<string, string> = {};
  const issues: string[] = [];
  const setIssue = (k: string, v: unknown) => {
    if (!(k in offer)) issues.push(k);
    offer[k] = String(v);
  };
  for (const t of epTicks) {
    const co = tickPayload(t).current_offer;
    if (co && typeof co === "object") for (const [k, v] of Object.entries(co)) setIssue(k, v);
  }
  for (const c of epCons) {
    const a = c.raw.assignments as Record<string, unknown> | undefined;
    if (a) for (const [k, v] of Object.entries(a)) setIssue(k, v);
  }

  // Agents (rows): joiners first, then any tick participants.
  const agents: string[] = [];
  const addAgent = (h?: unknown) => {
    if (typeof h === "string" && h && !agents.includes(h)) agents.push(h);
  };
  for (const j of joins.filter(j => episodeOf(j) === episode)) addAgent((j.raw.handle as string) ?? j.sender);
  for (const t of epTicks) addAgent(tickPayload(t).participant_id);

  // Rounds + per-cell moves.
  let maxRound = 0;
  const moves: Record<string, MoveAction> = {};
  for (const t of epTicks) {
    const p = tickPayload(t);
    const r = Number(p.round) || 0;
    const who = p.participant_id as string | undefined;
    const action = p.action as string | undefined;
    if (r > maxRound) maxRound = r;
    if (who && r && action) moves[`${who}#${r}`] = action;
  }

  let state: Negotiation["state"] = epTicks.length ? "negotiating" : "idle";
  let gar: number | undefined;
  if (epCons.length) {
    const c = epCons.at(-1)!;
    state = c.raw.broken === true ? "rejected" : "converged";
    const m = c.raw.metrics as Record<string, unknown> | undefined;
    if (typeof m?.gar === "number") gar = m.gar;
  }

  return {
    episode,
    issues,
    offer,
    agents,
    rounds: Math.max(maxRound, 1),
    currentRound: maxRound,
    moves,
    state,
    gar,
  };
}

function MoveGlyph({ action }: { action?: MoveAction }) {
  if (action === "propose")
    return <span title="propose" className="inline-block size-2.5 border-[1.5px] border-accent" />;
  if (action === "counter")
    return <span title="counter" className="inline-block size-2.5 rotate-45 border-[1.5px] border-accent" />;
  if (action === "accept")
    return <span title="accept" className="inline-block size-2.5 bg-green" />;
  if (action === "reject")
    return <X className="size-3 text-yellow" strokeWidth={2.5} aria-label="reject" />;
  if (action)
    return <span title={action} className="inline-block size-1.5 rounded-full bg-muted-foreground" />;
  return <span className="inline-block size-1 rounded-full bg-faint/40" aria-hidden />;
}

const STATE_TONE: Record<Negotiation["state"], string> = {
  idle: "var(--muted-foreground)",
  negotiating: "var(--accent)",
  converged: "var(--green)",
  rejected: "var(--yellow)",
};
const STATE_LABEL: Record<Negotiation["state"], string> = {
  idle: "Idle",
  negotiating: "Negotiating",
  converged: "Consensus",
  rejected: "No agreement",
};

export function NegotiationView({ events }: { events: readonly NegEvent[] }) {
  const neg = useMemo(() => derive(events), [events]);
  const converged = neg.state === "converged";

  if (neg.state === "idle") {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          icon={Scale}
          title="No active negotiation"
          description={
            <>
              Summon the aligner with <code className="font-mono text-accent">@aligner</code> to broker one.
              Offers, rounds, and convergence render here live.
            </>
          }
        />
      </div>
    );
  }

  const shortId = neg.episode ? neg.episode.split(":").pop() : null;
  const rounds = Array.from({ length: neg.rounds }, (_, i) => i + 1);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          {shortId && <span className="font-mono text-label text-muted-foreground">{shortId}</span>}
          <span className="text-label text-faint">Round</span>
          <span className="font-mono text-label tabular text-text">{neg.currentRound || "-"}</span>
          <span
            data-tour="consensus"
            className="ml-auto rounded px-2 py-0.5 text-micro font-semibold capitalize"
            style={{ color: STATE_TONE[neg.state], background: `color-mix(in srgb, ${STATE_TONE[neg.state]} 14%, transparent)` }}
          >
            {STATE_LABEL[neg.state]}
            {converged && neg.gar !== undefined ? ` · GAR ${neg.gar.toFixed(2)}` : ""}
          </span>
        </div>

        {/* Current Offer board */}
        <div data-tour="offer-board" className="mt-5">
          <div className="mb-2 text-micro uppercase tracking-wide text-faint">
            Current offer · {neg.issues.length} issue{neg.issues.length === 1 ? "" : "s"}
          </div>
          <div
            className="overflow-hidden rounded-xl border transition-colors"
            style={{
              borderColor: converged ? "var(--green)" : "var(--border2)",
              background: converged ? "color-mix(in srgb, var(--green) 6%, transparent)" : "transparent",
            }}
          >
            {neg.issues.length === 0 ? (
              <div className="px-4 py-6 text-center text-label text-muted-foreground">No offers yet</div>
            ) : (
              neg.issues.map((issue, i) => (
                <div
                  key={issue}
                  className="grid items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0"
                  style={{ gridTemplateColumns: "24px 1fr auto" }}
                >
                  <span className="font-mono text-micro tabular text-faint">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-label text-muted-foreground">{issue}</span>
                  <span
                    className="font-mono text-ui font-medium tabular transition-colors"
                    style={{ color: converged ? "var(--green)" : "var(--accent)" }}
                  >
                    {neg.offer[issue]}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Agent × Round swim lanes */}
        {neg.agents.length > 0 && (
          <div data-tour="swimlanes" className="mt-6">
            <div className="mb-2 flex items-center gap-4 text-micro uppercase tracking-wide text-faint">
              <span>Agent × round · aligner brokers</span>
              <span className="ml-auto flex items-center gap-3 normal-case tracking-normal">
                <Legend action="propose" label="propose" />
                <Legend action="counter" label="counter" />
                <Legend action="accept" label="accept" />
                <Legend action="reject" label="reject" />
              </span>
            </div>
            <div className="overflow-x-auto rounded-xl border border-border2">
              <div className="min-w-max">
                {/* header */}
                <div
                  className="grid border-b border-border"
                  style={{ gridTemplateColumns: `120px repeat(${neg.rounds}, minmax(40px, 1fr))` }}
                >
                  <div className="px-3 py-2 text-micro uppercase tracking-wide text-faint">Round →</div>
                  {rounds.map(r => (
                    <div
                      key={r}
                      className={`px-2 py-2 text-center font-mono text-micro tabular ${
                        r === neg.currentRound ? "bg-surface text-text" : "text-muted-foreground"
                      }`}
                    >
                      {String(r).padStart(2, "0")}
                    </div>
                  ))}
                </div>
                {/* agent rows */}
                {neg.agents.map(agent => (
                  <div
                    key={agent}
                    className="grid border-b border-border last:border-b-0"
                    style={{ gridTemplateColumns: `120px repeat(${neg.rounds}, minmax(40px, 1fr))` }}
                  >
                    <div className="truncate px-3 py-2.5 font-mono text-label text-text">{agent}</div>
                    {rounds.map(r => (
                      <div
                        key={r}
                        className={`flex items-center justify-center py-2.5 ${
                          r === neg.currentRound ? "bg-surface" : ""
                        }`}
                      >
                        <MoveGlyph action={neg.moves[`${agent}#${r}`]} />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ action, label }: { action: MoveAction; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-micro text-muted-foreground">
      <MoveGlyph action={action} />
      {label}
    </span>
  );
}
