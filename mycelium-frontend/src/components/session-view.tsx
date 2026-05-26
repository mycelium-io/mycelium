// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import { fetchMessages, getSSEUrl } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";

// ─── Types ────────────────────────────────────────────────────────────────────

interface RawMessage {
  id: string;
  room_name: string;
  sender_handle: string | null;
  recipient_handle: string | null;
  message_type: string;
  content: string | Record<string, unknown>;
  created_at: string;
}

type Action = "propose" | "counter" | "accept" | "reject" | "tick" | "consensus" | "broken" | "start" | "join";

interface Event {
  id: string;
  time: string;
  iso: string;
  agent: string;        // who acted (or who the tick was addressed to)
  round: number;
  action: Action;
  offer?: Record<string, string>;
  issueOptions?: Record<string, string[]>;
  note?: string;
  raw: RawMessage;
}

interface DerivedState {
  events: Event[];
  agents: string[];
  rounds: number;
  maxRounds: number;
  currentRound: number;
  currentOffer: Record<string, string> | null;
  issueOptions: Record<string, string[]> | null;
  proposerId: string | null;
  nextProposerId: string | null;
  state: "negotiating" | "complete" | "broken" | "starting";
  consensus: {
    plan: string;
    assignments: Record<string, string>;
    broken: boolean;
    planFile: string | null;
  } | null;
}

// ─── Parsing ──────────────────────────────────────────────────────────────────

function parseContent(c: string | Record<string, unknown>): Record<string, unknown> {
  if (typeof c === "string") {
    try { return JSON.parse(c); } catch { return { _text: c }; }
  }
  return c ?? {};
}

function parseEvents(messages: RawMessage[]): Event[] {
  const out: Event[] = [];
  // Track latest tick per agent so we can attribute their next 'direct' to the right round
  const lastTickFor = new Map<string, { round: number; iso: string }>();

  for (const m of messages) {
    const content = parseContent(m.content);
    const time = m.created_at.slice(11, 19);
    const iso = m.created_at;

    if (m.message_type === "coordination_start") {
      out.push({
        id: m.id, time, iso, agent: "CognitiveEngine",
        round: (content.round as number) ?? 0,
        action: "start",
        note: `${content.agent_count ?? "?"} agents`,
        raw: m,
      });
      continue;
    }

    if (m.message_type === "coordination_join") {
      const handle = String(content.handle ?? m.sender_handle ?? "?");
      const intent = typeof content.intent === "string" ? content.intent : undefined;
      out.push({
        id: m.id, time, iso, agent: handle,
        round: 0,
        action: "join",
        note: intent,
        raw: m,
      });
      continue;
    }

    if (m.message_type === "coordination_tick") {
      const payload = (content.payload as Record<string, unknown>) ?? content;
      const target = String(payload.participant_id ?? "?");
      const round = Number(payload.round ?? 0);
      lastTickFor.set(target, { round, iso });
      out.push({
        id: m.id, time, iso, agent: target,
        round,
        action: "tick",
        offer: payload.current_offer as Record<string, string> | undefined,
        issueOptions: payload.issue_options as Record<string, string[]> | undefined,
        note: `${payload.action ?? "respond"} · proposer=${payload.proposer_id ?? "—"}`,
        raw: m,
      });
      continue;
    }

    if (m.message_type === "coordination_consensus") {
      const broken = Boolean(content.broken);
      out.push({
        id: m.id, time, iso, agent: "CognitiveEngine",
        round: 0,
        action: broken ? "broken" : "consensus",
        offer: (content.assignments as Record<string, string>) ?? undefined,
        note: typeof content.plan === "string" ? content.plan : undefined,
        raw: m,
      });
      continue;
    }

    if (m.message_type === "direct" && m.sender_handle) {
      const action = String(content.action ?? "propose").toLowerCase();
      const lastTick = lastTickFor.get(m.sender_handle);
      const round = lastTick?.round ?? 0;
      let mapped: Action = "propose";
      if (action === "accept") mapped = "accept";
      else if (action === "reject") mapped = "reject";
      else if (action === "counter_offer" || action === "counter") mapped = "counter";
      else mapped = "propose";

      out.push({
        id: m.id, time, iso, agent: m.sender_handle,
        round,
        action: mapped,
        offer: content.offer as Record<string, string> | undefined,
        raw: m,
      });
    }
  }
  return out;
}

function deriveState(messages: RawMessage[]): DerivedState {
  const events = parseEvents(messages);

  // Agents: any sender_handle on a `direct`, plus participants from ticks
  const agents = new Set<string>();
  for (const e of events) {
    if (["propose", "counter", "accept", "reject", "tick"].includes(e.action)) {
      if (e.agent && e.agent !== "CognitiveEngine") agents.add(e.agent);
    }
  }

  // Rounds + current offer/options come from latest tick
  const ticks = events.filter(e => e.action === "tick");
  const lastTick = ticks[ticks.length - 1];
  const currentRound = lastTick?.round ?? 0;
  const rounds = currentRound;

  // Look at last tick payload for offer + options
  const lastTickRaw = lastTick?.raw;
  const tickContent = lastTickRaw ? parseContent(lastTickRaw.content) : {};
  const tickPayload = (tickContent.payload as Record<string, unknown>) ?? tickContent;

  const currentOffer = (lastTick?.offer ?? null) as Record<string, string> | null;
  const issueOptions = (lastTick?.issueOptions ?? null) as Record<string, string[]> | null;
  const proposerId = (tickPayload.proposer_id as string) ?? null;
  const nextProposerId = (tickPayload.next_proposer_id as string) ?? null;

  // State
  const consensusEvent = events.find(e => e.action === "consensus" || e.action === "broken");
  let state: DerivedState["state"] = "starting";
  if (consensusEvent) state = consensusEvent.action === "broken" ? "broken" : "complete";
  else if (lastTick) state = "negotiating";

  let consensus: DerivedState["consensus"] = null;
  if (consensusEvent) {
    const c = parseContent(consensusEvent.raw.content);
    consensus = {
      plan: String(c.plan ?? ""),
      assignments: (c.assignments as Record<string, string>) ?? {},
      broken: Boolean(c.broken),
      planFile: typeof c.plan_file === "string" ? c.plan_file : null,
    };
  }

  return {
    events, agents: Array.from(agents).sort(), rounds, maxRounds: 20, currentRound,
    currentOffer, issueOptions, proposerId, nextProposerId, state, consensus,
  };
}

// ─── Hook: live session messages ──────────────────────────────────────────────

function useSessionMessages(sessionRoom: string) {
  const [messages, setMessages] = useState<RawMessage[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchMessages(sessionRoom, 500).then((data: unknown) => {
      if (cancelled) return;
      const arr = Array.isArray(data) ? data : (data as { messages?: RawMessage[] })?.messages ?? [];
      // API returns newest-first; reverse to chronological.
      setMessages([...arr].reverse());
    }).catch(() => {});

    const url = getSSEUrl(sessionRoom);
    let es: EventSource | null = null;
    try {
      es = new EventSource(url);
      es.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as RawMessage;
          setMessages(prev => prev.some(m => m.id === msg.id) ? prev : [...prev, msg]);
        } catch { /* ignore non-message frames */ }
      };
      es.onerror = () => { /* SSE may flap; periodic refetch covers it */ };
    } catch { /* no-op */ }

    const refetch = setInterval(() => {
      fetchMessages(sessionRoom, 500).then((data: unknown) => {
        if (cancelled) return;
        const arr = Array.isArray(data) ? data : (data as { messages?: RawMessage[] })?.messages ?? [];
        setMessages([...arr].reverse());
      }).catch(() => {});
    }, 5000);

    return () => { cancelled = true; es?.close(); clearInterval(refetch); };
  }, [sessionRoom]);

  return messages;
}

// ─── Glyphs ───────────────────────────────────────────────────────────────────

const ACTION_META: Record<Action, { label: string; tone: "accent" | "ok" | "warn" | "muted" | "ink" }> = {
  start:     { label: "START",     tone: "muted" },
  join:      { label: "JOIN",      tone: "accent" },
  tick:      { label: "AWAITING",  tone: "accent" },
  propose:   { label: "PROPOSE",   tone: "ink" },
  counter:   { label: "COUNTER",   tone: "ink" },
  accept:    { label: "ACCEPT",    tone: "ok" },
  reject:    { label: "REJECT",    tone: "warn" },
  consensus: { label: "CONSENSUS", tone: "ok" },
  broken:    { label: "TIMEOUT",   tone: "warn" },
};

function toneVar(t: "accent" | "ok" | "warn" | "muted" | "ink"): string {
  return t === "accent" ? "var(--accent)"
       : t === "ok"     ? "var(--green)"
       : t === "warn"   ? "var(--yellow)"
       : t === "ink"    ? "var(--text)"
                        : "var(--muted)";
}

function ActionGlyph({ action }: { action: Action }) {
  const meta = ACTION_META[action];
  const color = toneVar(meta.tone);
  if (action === "reject" || action === "broken") {
    return (
      <svg
        width="12" height="12" viewBox="0 0 12 12"
        aria-hidden style={{ display: "inline-block", color, flexShrink: 0 }}
      >
        <line x1="2" y1="2" x2="10" y2="10" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <line x1="10" y1="2" x2="2" y2="10" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
    );
  }
  if (action === "tick") {
    // "waiting on this agent" — pulse to read as in-progress
    return (
      <span
        aria-hidden
        title="awaiting response"
        style={{
          display: "inline-block", width: 6, height: 6, borderRadius: "50%",
          background: "var(--accent)",
          animation: "myc-pulse 1.4s ease-in-out infinite",
        }}
      />
    );
  }
  if (action === "counter") {
    // Hollow diamond — distinct from PROPOSE (square) but same geometric family
    return (
      <span
        aria-hidden
        style={{
          display: "inline-block", width: 11, height: 11,
          background: "transparent",
          border: `1.5px solid ${color}`,
          transform: "rotate(45deg)",
          flexShrink: 0,
        }}
      />
    );
  }
  const filled = action === "accept" || action === "consensus";
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block", width: 11, height: 11,
        background: filled ? color : "transparent",
        border: `1.5px solid ${color}`,
      }}
    />
  );
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

function HeaderRow({ sessionRoom, derived }: { sessionRoom: string; derived: DerivedState }) {
  const sigil = sessionRoom.split(":").pop() ?? sessionRoom;
  const stateColor =
    derived.state === "complete" ? "var(--green)" :
    derived.state === "broken"   ? "var(--yellow)" :
    derived.state === "negotiating" ? "var(--accent)" :
                                      "var(--muted)";
  const stateLabel =
    derived.state === "complete" ? "CONSENSUS" :
    derived.state === "broken"   ? "TIMEOUT" :
    derived.state === "negotiating" ? "NEGOTIATING" :
                                      "STARTING";
  const awaiting = derived.state === "negotiating" && derived.nextProposerId
    ? `awaiting ${derived.nextProposerId}` : null;

  return (
    <div className="grid items-end gap-6 px-6 py-4 border-b border-border2"
         style={{ gridTemplateColumns: "1fr auto 1fr" }}>
      <div>
        <div className="caps-mono-sm text-muted">SESSION ID</div>
        <div className="font-mono text-display text-text mt-1 truncate" style={{ lineHeight: 1.1 }}>
          {sigil}
        </div>
        <div className="caps-mono-sm text-muted mt-1">
          {derived.agents.length} agents · {derived.events.length} events
        </div>
      </div>
      <div className="text-center">
        <div className="caps-mono-sm text-muted">ROUND</div>
        <div style={{ lineHeight: 1, marginTop: 4 }}>
          <span style={{ color: "var(--accent)", fontFamily: "'SF Mono', monospace", fontSize: 56, fontWeight: 700, letterSpacing: "0.02em" }}>
            {String(derived.currentRound).padStart(2, "0")}
          </span>
          <span style={{ color: "var(--dim)", fontFamily: "'SF Mono', monospace", fontSize: 28, fontWeight: 400 }}>
            {" "}/ {derived.maxRounds}
          </span>
        </div>
      </div>
      <div className="text-right">
        <div className="caps-mono-sm text-muted">STATE</div>
        <div className="caps-mono mt-1" style={{ color: stateColor }}>{stateLabel}</div>
        {awaiting && <div className="caps-mono-sm text-muted italic mt-1">{awaiting}</div>}
      </div>
    </div>
  );
}

function NegotiationSpace({ derived }: { derived: DerivedState }) {
  const offer = derived.currentOffer;
  const options = derived.issueOptions;
  const [expanded, setExpanded] = useState(false);

  if (!offer || !options) {
    return (
      <div className="px-6 py-4 border-b border-border">
        <div className="caps-mono-sm text-muted mb-2">CURRENT OFFER</div>
        <div className="text-body text-muted italic">no offer yet — waiting for first tick</div>
      </div>
    );
  }
  const issues = Object.keys(options);

  return (
    <div className="px-6 py-4 border-b border-border">
      <div className="flex items-center gap-3 mb-2">
        <span className="caps-mono-sm text-muted">CURRENT OFFER · {issues.length} ISSUES</span>
        <button
          onClick={() => setExpanded(e => !e)}
          className="ml-auto flex items-center gap-1.5 caps-mono-sm text-text2 hover:text-accent transition-colors"
          aria-expanded={expanded}
        >
          <span aria-hidden style={{ fontSize: 11 }}>{expanded ? "−" : "+"}</span>
          {expanded ? "HIDE OPTIONS" : "SHOW ALL OPTIONS"}
        </button>
      </div>
      <div
        className="border border-border2 grid items-baseline gap-x-3 px-4"
        style={{ background: "rgba(255,255,255,0.015)", gridTemplateColumns: "max-content 24px 1fr" }}
      >
        {issues.map((issue, i) => {
          const current = offer[issue];
          const opts = options[issue] ?? [];
          return (
            <Fragment key={issue}>
              {i > 0 && <div className="border-t border-border" style={{ gridColumn: "1 / -1" }} />}
              <span className="caps-mono-sm text-muted whitespace-nowrap py-2.5">
                {String(i + 1).padStart(2, "0")} · {issue}
              </span>
              <span className="text-dim caps-mono-sm text-center py-2.5">=</span>
              <span className="font-mono text-body text-accent break-words py-2.5" style={{ fontWeight: 600 }}>
                {current ?? "—"}
              </span>
              {expanded && opts.length > 0 && (
                <div className="pb-2.5 space-y-0.5" style={{ gridColumn: "3 / -1" }}>
                  {opts.filter(o => o !== current).map(opt => (
                    <div key={opt} className="flex items-start gap-2">
                      <span
                        aria-hidden
                        style={{
                          width: 7, height: 7, marginTop: 7, flexShrink: 0,
                          border: "1.5px solid var(--muted)",
                        }}
                      />
                      <span className="font-mono text-label text-text2 leading-snug break-words">{opt}</span>
                    </div>
                  ))}
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

function SwimLanes({ derived }: { derived: DerivedState }) {
  const { agents, currentRound, maxRounds, events } = derived;
  const rounds = Math.max(maxRounds, currentRound + 1);

  // Build per-agent, per-round latest action (preferring agent response over tick)
  const lanes = useMemo(() => {
    const m = new Map<string, Map<number, Action>>();
    for (const a of agents) m.set(a, new Map());
    for (const e of events) {
      if (e.agent === "CognitiveEngine") continue;
      const lane = m.get(e.agent);
      if (!lane) continue;
      const existing = lane.get(e.round);
      // Don't overwrite a real response with a later tick
      if (existing && existing !== "tick" && e.action === "tick") continue;
      lane.set(e.round, e.action);
    }
    return m;
  }, [agents, events]);

  if (agents.length === 0) {
    return (
      <div className="px-6 py-4 border-b border-border">
        <div className="caps-mono-sm text-muted mb-2">SWIM LANES · AGENT × ROUND</div>
        <div className="text-body text-muted italic">no agents have joined yet</div>
      </div>
    );
  }

  return (
    <div className="px-6 py-4 border-b border-border">
      <div className="caps-mono-sm text-muted mb-2">SWIM LANES · AGENT × ROUND</div>
      <div className="border border-border2" style={{ background: "rgba(255,255,255,0.015)" }}>
       <ScrollArea className="w-full overflow-hidden">
        {/* Round axis */}
        <div className="grid border-b border-border2" style={{ gridTemplateColumns: `140px repeat(${rounds}, minmax(40px, 1fr))`, minWidth: "max-content" }}>
          <div className="px-3 py-2 caps-mono-sm text-muted">ROUND →</div>
          {Array.from({ length: rounds }).map((_, i) => {
            const r = i + 1;
            const isCur = r === currentRound;
            const isPast = r < currentRound;
            return (
              <div key={i} className="text-center py-2 border-l border-border tabular"
                   style={{
                     fontSize: "var(--text-micro)",
                     color: isPast ? "var(--accent)" : isCur ? "var(--text)" : "var(--dim)",
                     fontWeight: isPast || isCur ? 600 : 400,
                     background: isCur ? "rgba(93,212,224,0.06)" : undefined,
                   }}>
                {String(r).padStart(2, "0")}
              </div>
            );
          })}
        </div>
        {/* Lanes */}
        {agents.map(agent => (
          <div key={agent} className="grid border-b border-border last:border-b-0"
               style={{ gridTemplateColumns: `140px repeat(${rounds}, minmax(40px, 1fr))`, minWidth: "max-content" }}>
            <div className="px-3 py-2 flex items-center border-r border-border2 min-w-0">
              <span className="font-mono text-label text-text truncate">{agent}</span>
            </div>
            {Array.from({ length: rounds }).map((_, i) => {
              const r = i + 1;
              const action = lanes.get(agent)?.get(r);
              return (
                <div key={i} className="flex items-center justify-center border-l border-border"
                     style={{ height: 38, background: r === currentRound ? "rgba(93,212,224,0.06)" : undefined }}>
                  {action && <ActionGlyph action={action} />}
                </div>
              );
            })}
          </div>
        ))}
       </ScrollArea>
        {/* Legend */}
        <div className="flex gap-5 px-4 py-2 border-t border-border2 bg-bg/60">
          {(["propose", "counter", "accept", "reject"] as Action[]).map(a => (
            <div key={a} className="flex items-center gap-2">
              <ActionGlyph action={a} />
              <span className="caps-mono-sm" style={{ color: toneVar(ACTION_META[a].tone) }}>
                {ACTION_META[a].label}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ConsensusBanner({ derived }: { derived: DerivedState }) {
  const c = derived.consensus;
  if (!c) return null;
  const tone = c.broken ? "warn" : "ok";
  const color = toneVar(tone);
  return (
    <div className="mx-6 my-4 border" style={{
      borderColor: color,
      background: c.broken ? "rgba(251,191,36,0.04)" : "rgba(52,211,153,0.04)",
      padding: 16,
    }}>
      <div className="flex items-center gap-2 mb-2">
        <ActionGlyph action={c.broken ? "broken" : "consensus"} />
        <span className="caps-mono" style={{ color }}>
          {c.broken ? "NEGOTIATION TIMEOUT" : "CONSENSUS REACHED"}
        </span>
      </div>
      {c.plan && <div className="text-body text-text2 mb-2">{c.plan}</div>}
      {Object.keys(c.assignments).length > 0 && (
        <div
          className="font-mono text-label mt-2 grid items-baseline gap-x-3 gap-y-1"
          style={{ gridTemplateColumns: "max-content max-content 1fr" }}
        >
          {Object.entries(c.assignments).map(([k, v]) => (
            <Fragment key={k}>
              <span style={{ color }}>{k}</span>
              <span className="text-dim">=</span>
              <span className="text-text">{String(v)}</span>
            </Fragment>
          ))}
        </div>
      )}
      {!c.broken && c.planFile && (
        <div className="caps-mono-sm mt-3 pt-2 border-t" style={{ borderColor: color, color }}>
          compiled into the room plan → {c.planFile}
        </div>
      )}
    </div>
  );
}

function EventLog({ derived }: { derived: DerivedState }) {
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const events = order === "desc" ? [...derived.events].reverse() : derived.events;
  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-paper flex-shrink-0">
        <span className="caps-mono-sm text-muted">EVENT LOG · {derived.events.length}</span>
        <button
          onClick={() => setOrder(o => o === "desc" ? "asc" : "desc")}
          className="ml-auto flex items-center gap-1.5 caps-mono-sm text-text2 hover:text-accent transition-colors"
          title={order === "desc" ? "Showing newest first — click for oldest first" : "Showing oldest first — click for newest first"}
        >
          <span aria-hidden style={{ fontSize: 11 }}>{order === "desc" ? "↓" : "↑"}</span>
          {order === "desc" ? "NEWEST" : "OLDEST"}
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {events.map(e => <EventRow key={e.id} event={e} />)}
        {events.length === 0 && (
          <div className="px-6 py-8 caps-mono-sm text-muted italic text-center">no events yet</div>
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: Event }) {
  const meta = ACTION_META[event.action];
  const color = toneVar(meta.tone);
  return (
    <div className="px-4 py-2 border-b border-border hover:bg-white/[0.02]">
      {/* Top row: time · R## · agent · action */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-micro text-muted tabular font-mono flex-shrink-0">{event.time}</span>
        <span className="text-micro text-dim tabular font-mono flex-shrink-0">R{String(event.round).padStart(2, "0")}</span>
        <span className="font-mono text-label text-text2 truncate min-w-0 flex-1">{event.agent}</span>
        <span className="flex items-center gap-1.5 flex-shrink-0">
          <ActionGlyph action={event.action} />
          <span className="caps-mono-sm" style={{ color }}>{meta.label}</span>
        </span>
      </div>
      {/* Detail */}
      {event.note && (
        <div className="text-label text-text2 italic mt-1 pl-[58px]">{event.note}</div>
      )}
      {event.offer && Object.keys(event.offer).length > 0 && (
        <div className="font-mono text-micro mt-1 pl-[58px] space-y-0.5">
          {Object.entries(event.offer).slice(0, 4).map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-2 min-w-0">
              <span className="text-muted truncate flex-shrink-0" style={{ maxWidth: 110 }}>{k}</span>
              <span className="text-dim flex-shrink-0">=</span>
              <span className="text-text2 truncate min-w-0">{String(v)}</span>
            </div>
          ))}
          {Object.keys(event.offer).length > 4 && (
            <div className="text-dim italic">…and {Object.keys(event.offer).length - 4} more</div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

interface SessionViewProps {
  sessionRoom: string;
}

export function SessionView({ sessionRoom }: SessionViewProps) {
  const messages = useSessionMessages(sessionRoom);
  const derived = useMemo(() => deriveState(messages), [messages]);

  return (
    <PanelGroup
      orientation="horizontal"
      className="flex-1"
      style={{ width: "100%", height: "100%" }}
    >
      <Panel id="main" defaultSize={60} minSize={25} className="overflow-hidden" style={{ minWidth: 0 }}>
        <ScrollArea className="h-full w-full" style={{ minWidth: 0 }}>
          <HeaderRow sessionRoom={sessionRoom} derived={derived} />
          <SwimLanes derived={derived} />
          <NegotiationSpace derived={derived} />
          {derived.consensus && <ConsensusBanner derived={derived} />}
        </ScrollArea>
      </Panel>
      <PanelResizeHandle
        className="w-px bg-border hover:bg-accent transition-colors flex-shrink-0 relative"
        style={{ cursor: "col-resize" }}
      >
        {/* invisible wider hit-target so dragging is forgiving */}
        <span aria-hidden className="absolute inset-y-0 -left-1.5 -right-1.5" />
      </PanelResizeHandle>
      <Panel id="log" defaultSize={40} minSize={20} className="overflow-hidden" style={{ minWidth: 0 }}>
        <aside className="h-full bg-surface/40 flex flex-col overflow-hidden">
          <EventLog derived={derived} />
        </aside>
      </Panel>
    </PanelGroup>
  );
}
