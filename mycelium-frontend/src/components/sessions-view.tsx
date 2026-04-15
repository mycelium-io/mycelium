// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchChildRooms, fetchMessages, getSSEUrl } from "@/lib/api";

interface ChildSession {
  name: string;
  coordination_state: string;
  created_at: string;
  parent_namespace?: string;
  join_deadline?: string | null;
}

interface Event {
  id: string;
  type: string;
  sender: string;
  time: string;
  raw: Record<string, unknown>;
  rawMessage: Record<string, unknown>;
}

const stateColors: Record<string, { dot: string; label: string }> = {
  idle:        { dot: "bg-muted/40",       label: "text-muted" },
  waiting:     { dot: "bg-yellow-400",     label: "text-yellow-300" },
  negotiating: { dot: "bg-accent",         label: "text-accent" },
  complete:    { dot: "bg-emerald-400",    label: "text-emerald-300" },
  failed:      { dot: "bg-red-400",        label: "text-red-300" },
};

function parseSessionEvent(msg: Record<string, unknown>): Event {
  let mtype = (msg.message_type as string) || (msg.type as string) || "unknown";
  const sender = (msg.sender_handle as string) || (msg.updated_by as string) || "?";
  const created = (msg.created_at as string) || new Date().toISOString();
  const time = created.slice(11, 19);

  let raw: Record<string, unknown> = {};
  try {
    if (typeof msg.content === "string") {
      raw = JSON.parse(msg.content);
    } else if (msg.content && typeof msg.content === "object") {
      raw = msg.content as Record<string, unknown>;
    } else {
      raw = {};
    }
  } catch {
    raw = { text: msg.content as string };
  }

  // coordination_tick wraps everything under .payload
  if (mtype === "coordination_tick" && raw && typeof raw === "object" && raw.payload) {
    raw = raw.payload as Record<string, unknown>;
  }

  // Direct/broadcast messages with an action field are negotiation responses
  if (
    (mtype === "direct" || mtype === "broadcast") &&
    raw && typeof raw === "object" &&
    ("action" in raw || "offer" in raw)
  ) {
    mtype = "negotiate_response";
    if (!("action" in raw) && "offer" in raw) {
      raw.action = "counter_offer";
    }
  }

  return {
    id: `${msg.id || Date.now()}-${Math.random()}`,
    type: mtype,
    sender,
    time,
    raw,
    rawMessage: msg,
  };
}

// ── Card components ──────────────────────────────────────────────────────────

function OfferBlock({ offer, tone = "indigo" }: { offer: Record<string, unknown>; tone?: "indigo" | "emerald" | "fuchsia" }) {
  const toneColors = {
    indigo:   "text-indigo-300",
    emerald:  "text-emerald-300",
    fuchsia:  "text-fuchsia-300",
  };
  const entries = Object.entries(offer);
  if (entries.length === 0) return null;
  return (
    <div className="text-xs font-mono bg-black/30 rounded p-2 space-y-0.5 mt-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2 items-start">
          <span className={toneColors[tone]}>{k}</span>
          <span className="text-muted/40">=</span>
          <span className="text-white/80 break-all">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}

function JoinCard({ event }: { event: Event }) {
  const handle = (event.raw.handle as string) || event.sender;
  const intent = event.raw.intent as string | undefined;
  return (
    <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-bold uppercase tracking-wider">joined</span>
        <span className="font-mono text-sm text-cyan-200 font-semibold">{handle}</span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
      {intent && (
        <p className="text-sm text-white/85 leading-relaxed whitespace-pre-wrap">{intent}</p>
      )}
    </div>
  );
}

function StartCard({ event }: { event: Event }) {
  const count = (event.raw.agent_count as number) ?? "?";
  return (
    <div className="bg-cyan-500/5 border border-cyan-500/30 rounded-lg p-3">
      <div className="flex items-center gap-2">
        <span className="text-cyan-300 font-bold uppercase tracking-wider text-xs">Session started</span>
        <span className="text-xs text-muted">{count} agents</span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
    </div>
  );
}

function TickCard({ event }: { event: Event }) {
  const raw = event.raw;
  const round = (raw.round as number | string | undefined) ?? "?";
  const participant = (raw.participant_id as string) || "?";
  const canCounter = raw.can_counter_offer as boolean;
  const action = raw.action as string;
  const currentOffer = raw.current_offer as Record<string, unknown> | undefined;
  const allowed = (raw.allowed_actions as string[]) || [];

  return (
    <div className="bg-indigo-500/5 border border-indigo-500/20 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 font-bold uppercase tracking-wider whitespace-nowrap">
          round {round}
        </span>
        <span className="font-mono text-sm text-indigo-200 font-semibold">{participant}</span>
        <span className="text-[11px] text-muted/60">{action === "respond" ? "to respond" : action}</span>
        {canCounter && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-500/15 text-fuchsia-300 font-bold uppercase tracking-wider whitespace-nowrap">
            can counter
          </span>
        )}
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
      {allowed.length > 0 && (
        <div className="flex gap-1 mt-1 flex-wrap">
          {allowed.map((a) => (
            <span key={a} className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-muted/80 font-mono uppercase tracking-wider">
              {a}
            </span>
          ))}
        </div>
      )}
      {currentOffer && Object.keys(currentOffer).length > 0 && (
        <>
          <div className="text-muted/50 uppercase tracking-wider text-[9px] mt-2">current offer</div>
          <OfferBlock offer={currentOffer} tone="indigo" />
        </>
      )}
    </div>
  );
}

function ResponseCard({ event }: { event: Event }) {
  const action = (event.raw.action as string) || "reject";
  const offer = event.raw.offer as Record<string, unknown> | undefined;

  const styles = {
    accept:        { border: "border-emerald-500/30", bg: "bg-emerald-500/5",  chip: "bg-emerald-500/15 text-emerald-300", icon: "✓", text: "accepted" },
    reject:        { border: "border-red-500/30",     bg: "bg-red-500/5",      chip: "bg-red-500/15 text-red-300",         icon: "✗", text: "rejected" },
    counter_offer: { border: "border-fuchsia-500/30", bg: "bg-fuchsia-500/5",  chip: "bg-fuchsia-500/15 text-fuchsia-300", icon: "↻", text: "counter-offered" },
  };
  const s = styles[action as keyof typeof styles] || styles.reject;

  return (
    <div className={`${s.bg} border ${s.border} rounded-lg p-3`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-base leading-none">{s.icon}</span>
        <span className="font-mono text-sm text-white/90 font-semibold">{event.sender}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider whitespace-nowrap ${s.chip}`}>
          {s.text}
        </span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
      {offer && <OfferBlock offer={offer} tone="fuchsia" />}
    </div>
  );
}

function ConsensusCard({ event }: { event: Event }) {
  const plan = event.raw.plan as string | undefined;
  const assignments = event.raw.assignments as Record<string, unknown> | undefined;
  const broken = event.raw.broken as boolean | undefined;
  const hasAssignments = assignments && Object.keys(assignments).length > 0;

  if (broken) {
    return (
      <div className="bg-red-500/5 border border-red-500/40 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-red-400 text-lg leading-none">✗</span>
          <span className="text-red-300 font-bold uppercase tracking-wider text-xs">Negotiation failed</span>
          <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
        </div>
        {plan && <p className="text-sm text-white/90 leading-relaxed whitespace-pre-wrap">{plan}</p>}
      </div>
    );
  }

  return (
    <div className="bg-emerald-500/5 border border-emerald-500/40 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-emerald-400 text-lg leading-none">✓</span>
        <span className="text-emerald-300 font-bold uppercase tracking-wider text-xs">Consensus reached</span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
      {plan && <p className="text-sm text-white/90 mb-2 leading-relaxed whitespace-pre-wrap">{plan}</p>}
      {hasAssignments && <OfferBlock offer={assignments} tone="emerald" />}
    </div>
  );
}

function ChatCard({ event }: { event: Event }) {
  const text = (event.raw.text as string) || (event.rawMessage.content as string) || "";
  return (
    <div className="py-2 border-b border-border/20">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="font-mono text-sm text-sky-300 font-semibold">{event.sender}</span>
        <span className="text-[10px] text-muted/50 uppercase">{event.type}</span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
      <p className="text-sm text-white/90 whitespace-pre-wrap leading-relaxed">{text}</p>
    </div>
  );
}

function GenericCard({ event }: { event: Event }) {
  const preview = JSON.stringify(event.raw).slice(0, 120);
  return (
    <div className="border-l-2 border-l-muted/30 pl-3 py-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-muted/10 text-muted">
          {event.type}
        </span>
        <span className="flex-1 text-xs text-muted/70 font-mono truncate" title={preview}>{preview}</span>
        <span className="text-[10px] text-muted/40 font-mono">{event.time}</span>
      </div>
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-2 px-3 py-3 text-xs text-indigo-300/80">
      <span className="flex gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: "0ms" }} />
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: "200ms" }} />
        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" style={{ animationDelay: "400ms" }} />
      </span>
      <span className="italic">CognitiveEngine is thinking…</span>
    </div>
  );
}

function renderEvent(event: Event) {
  switch (event.type) {
    case "coordination_join":      return <JoinCard event={event} />;
    case "coordination_start":     return <StartCard event={event} />;
    case "coordination_tick":      return <TickCard event={event} />;
    case "negotiate_response":     return <ResponseCard event={event} />;
    case "coordination_consensus": return <ConsensusCard event={event} />;
    case "broadcast":
    case "direct":
    case "announce":
    case "delegate":               return <ChatCard event={event} />;
    default:                       return <GenericCard event={event} />;
  }
}

// ── Session feed (one session) ───────────────────────────────────────────────

function SessionFeed({ sessionName }: { sessionName: string }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setEvents([]);
    fetchMessages(sessionName).then((data) => {
      const msgs = (data.messages || []).reverse();
      setEvents(msgs.map(parseSessionEvent));
    }).catch(() => {});
  }, [sessionName]);

  useEffect(() => {
    const url = getSSEUrl(sessionName);
    let es: EventSource;
    let retryTimeout: NodeJS.Timeout;

    function connect() {
      es = new EventSource(url);
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          setEvents((prev) => [...prev, parseSessionEvent(msg)]);
        } catch {}
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        retryTimeout = setTimeout(connect, 5000);
      };
    }
    connect();
    return () => { es?.close(); clearTimeout(retryTimeout); };
  }, [sessionName]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border/50">
        <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
        <span className="text-[10px] text-muted/60 font-mono">{connected ? "live" : "reconnecting"}</span>
        <span className="text-[10px] text-muted/40 font-mono truncate" title={sessionName}>{sessionName}</span>
        <span className="ml-auto text-[10px] text-muted/40 font-mono">{events.length}</span>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {events.length === 0 ? (
          <div className="text-center text-muted/50 py-20 text-sm">No events yet</div>
        ) : (
          <>
            {events.map((ev) => <div key={ev.id}>{renderEvent(ev)}</div>)}
            {(() => {
              const last = events[events.length - 1];
              const thinking = last && (last.type === "coordination_start" || last.type === "negotiate_response");
              return thinking ? <ThinkingIndicator /> : null;
            })()}
          </>
        )}
      </div>
    </div>
  );
}

// ── Top-level SessionsView ───────────────────────────────────────────────────

interface Props {
  roomName: string;
}

export function SessionsView({ roomName }: Props) {
  const [sessions, setSessions] = useState<ChildSession[]>([]);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const rooms = await fetchChildRooms(roomName);
      if (cancelled) return;
      // newest first
      const sorted = [...rooms].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setSessions(sorted);
      setActive((cur) => cur ?? sorted[0]?.name ?? null);
    };
    load();
    const id = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [roomName]);

  const activeSession = useMemo(() => sessions.find((s) => s.name === active), [sessions, active]);

  if (sessions.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center text-muted/60 text-sm px-6">
        <div className="mb-2">No sessions in this room</div>
        <div className="text-xs text-muted/40 font-mono">
          Spawn one with <code className="text-accent/70">mycelium session join</code>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* VSCode-style tab strip */}
      <div className="flex items-stretch border-b border-border overflow-x-auto bg-surface/40 shrink-0">
        {sessions.map((s) => {
          const isActive = active === s.name;
          const shortId = s.name.split(":session:")[1] || s.name;
          const state = stateColors[s.coordination_state] || stateColors.idle;
          return (
            <button
              key={s.name}
              onClick={() => setActive(s.name)}
              className={`group relative flex items-center gap-2 px-3 py-2 text-xs font-mono border-r border-border/60 transition-colors whitespace-nowrap ${
                isActive
                  ? "bg-bg text-white"
                  : "text-muted/70 hover:text-white hover:bg-white/5"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${state.dot}`} />
              <span>{shortId}</span>
              <span className={`text-[9px] uppercase tracking-wider ${state.label}`}>{s.coordination_state}</span>
              {isActive && (
                <span className="absolute left-0 right-0 bottom-0 h-[2px] bg-accent" />
              )}
            </button>
          );
        })}
      </div>

      {/* Active session feed */}
      <div className="flex-1 overflow-hidden">
        {activeSession ? (
          <SessionFeed key={activeSession.name} sessionName={activeSession.name} />
        ) : (
          <div className="text-center text-muted/50 py-20 text-sm">Pick a session</div>
        )}
      </div>
    </div>
  );
}
