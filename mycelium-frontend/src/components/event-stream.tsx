// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getSSEUrl, fetchMessages, fetchChildRooms } from "@/lib/api";
import { SessionsView } from "./sessions-view";

interface Event {
  id: string;
  type: string;
  content: string;
  sender: string;
  recipient: string | null;
  time: string;
  raw: Record<string, unknown>;
}

const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

function parseEvent(msg: Record<string, unknown>): Event {
  const mtype = (msg.message_type as string) || (msg.type as string) || "unknown";
  const sender = (msg.sender_handle as string) || (msg.updated_by as string) || "?";
  const recipient = (msg.recipient_handle as string) || null;
  const created = (msg.created_at as string) || new Date().toISOString();
  const time = created.slice(11, 19);

  let content = "";
  let raw: Record<string, unknown> = {};

  try {
    if (typeof msg.content === "string") {
      // Chat messages carry a plain string in content; coordination events
      // carry a JSON blob. Try to parse, fall back to the raw string.
      if (CHAT_TYPES.has(mtype)) {
        raw = { text: msg.content };
      } else {
        raw = JSON.parse(msg.content);
      }
    } else if (msg.content) {
      raw = msg.content as Record<string, unknown>;
    } else {
      raw = msg;
    }
  } catch {
    raw = CHAT_TYPES.has(mtype) ? { text: msg.content } : msg;
  }

  switch (mtype) {
    case "broadcast":
    case "direct":
    case "announce":
    case "delegate":
      content = (raw.text as string) || (msg.content as string) || "";
      break;
    case "coordination_join": {
      const handle = (raw.handle as string) || sender;
      const intent = raw.intent as string;
      content = `${handle} joined${intent ? ` — ${intent}` : ""}`;
      break;
    }
    case "coordination_start":
      content = `Session started — ${raw.agent_count || "?"} agents`;
      break;
    case "coordination_tick": {
      // Ticks wrap their fields under .payload
      const tick = (raw.payload as Record<string, unknown>) || raw;
      const round = tick.round ?? "?";
      const action = tick.action ?? "tick";
      const participant = tick.participant_id ?? "?";
      content = `Round ${round}: ${participant} → ${action}`;
      if (tick.current_offer) content += ` ${JSON.stringify(tick.current_offer)}`;
      break;
    }
    case "coordination_consensus": {
      const plan = raw.plan as string;
      const assignments = raw.assignments as Record<string, string>;
      content = plan || "";
      if (assignments) content += " " + Object.entries(assignments).map(([k, v]) => `${k}=${v}`).join(", ");
      break;
    }
    case "memory_changed": {
      const key = (raw.key || msg.key) as string;
      const version = (raw.version || msg.version) as number;
      const by = (raw.updated_by || msg.updated_by) as string;
      content = `${key} v${version} by ${by}`;
      break;
    }
    case "synthesis_complete":
      content = `→ ${raw.synthesis_key || "?"}`;
      break;
    default:
      content = (msg.content as string) || JSON.stringify(msg).slice(0, 100);
  }

  return {
    id: `${Date.now()}-${Math.random()}`,
    type: mtype,
    content,
    sender,
    recipient,
    time,
    raw,
  };
}

const typeStyles: Record<string, { border: string; badge: string; badgeText: string }> = {
  broadcast:              { border: "border-l-sky-400",     badge: "bg-sky-500/10 text-sky-300",      badgeText: "broadcast" },
  direct:                 { border: "border-l-sky-400",     badge: "bg-sky-500/15 text-sky-200",      badgeText: "direct" },
  announce:               { border: "border-l-sky-300",     badge: "bg-sky-500/10 text-sky-200",      badgeText: "announce" },
  delegate:               { border: "border-l-fuchsia-400", badge: "bg-fuchsia-500/10 text-fuchsia-300", badgeText: "delegate" },
  coordination_join:      { border: "border-l-cyan-400",    badge: "bg-cyan-500/10 text-cyan-400",    badgeText: "join" },
  coordination_start:     { border: "border-l-cyan-400",    badge: "bg-cyan-500/15 text-cyan-300",    badgeText: "start" },
  coordination_tick:      { border: "border-l-indigo-400",  badge: "bg-indigo-500/10 text-indigo-400", badgeText: "tick" },
  coordination_consensus: { border: "border-l-emerald-400", badge: "bg-emerald-500/10 text-emerald-400", badgeText: "consensus" },
  memory_changed:         { border: "border-l-yellow-400",  badge: "bg-yellow-500/10 text-yellow-400", badgeText: "memory" },
  synthesis_complete:     { border: "border-l-emerald-400", badge: "bg-emerald-500/10 text-emerald-400", badgeText: "synthesis" },
};

const defaultStyle = { border: "border-l-muted", badge: "bg-muted/10 text-muted", badgeText: "msg" };

const MENTION_RE = /(@[\w-]+)/g;

function renderWithMentions(text: string): React.ReactNode {
  // split() with a capturing group returns alternating [non-match, match, ...].
  // Odd indices are the @handles; this avoids the stateful .test() gotcha.
  const parts = text.split(MENTION_RE);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className="text-accent font-semibold">{part}</span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

type View = "channel" | "events" | "sessions";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
}

export function EventStream({ roomName, onMemoryChanged }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);
  const [view, setView] = useState<View>("channel");
  const [sessionCount, setSessionCount] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Poll child sessions for the tab count
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const rooms = await fetchChildRooms(roomName);
        if (!cancelled) setSessionCount(rooms.length);
      } catch {}
    };
    load();
    const id = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [roomName]);

  // Load initial messages
  useEffect(() => {
    fetchMessages(roomName).then(data => {
      const msgs = (data.messages || []).reverse();
      setEvents(msgs.map(parseEvent));
    }).catch(() => {});
  }, [roomName]);

  // SSE connection
  useEffect(() => {
    const url = getSSEUrl(roomName);
    let es: EventSource;
    let retryTimeout: NodeJS.Timeout;

    function connect() {
      es = new EventSource(url);
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          const event = parseEvent(msg);
          setEvents(prev => [...prev, event]);
          if (event.type === "memory_changed") onMemoryChanged?.();
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
  }, [roomName, onMemoryChanged]);

  const visible = useMemo(
    () => (view === "channel" ? events.filter(e => CHAT_TYPES.has(e.type)) : events),
    [events, view],
  );

  // Auto-scroll when new events arrive
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visible]);

  const channelCount = useMemo(
    () => events.filter(e => CHAT_TYPES.has(e.type)).length,
    [events],
  );

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border shrink-0">
        <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
        <span className="text-xs text-muted font-mono">{connected ? "connected" : "reconnecting..."}</span>
        <div className="ml-auto flex gap-1">
          <button
            onClick={() => setView("channel")}
            className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors ${
              view === "channel"
                ? "bg-sky-500/15 text-sky-300"
                : "text-muted/60 hover:text-white"
            }`}
          >
            Channel <span className="text-muted/50">({channelCount})</span>
          </button>
          <button
            onClick={() => setView("events")}
            className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors ${
              view === "events"
                ? "bg-accent/15 text-accent"
                : "text-muted/60 hover:text-white"
            }`}
          >
            Events <span className="text-muted/50">({events.length})</span>
          </button>
          <button
            onClick={() => setView("sessions")}
            className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded transition-colors ${
              view === "sessions"
                ? "bg-indigo-500/15 text-indigo-300"
                : "text-muted/60 hover:text-white"
            }`}
          >
            Sessions <span className="text-muted/50">({sessionCount})</span>
          </button>
        </div>
      </div>
      {view === "sessions" ? (
        <div className="flex-1 overflow-hidden">
          <SessionsView roomName={roomName} />
        </div>
      ) : (
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {visible.length === 0 && (
          <div className="text-center text-muted/50 py-20 text-sm">
            {view === "channel" ? "No channel messages yet" : "Waiting for events..."}
          </div>
        )}
        {view === "channel"
          ? visible.map(ev => (
              <div key={ev.id} className="py-2 border-b border-border/20 last:border-b-0">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-mono text-sm text-sky-300 font-semibold">{ev.sender}</span>
                  {ev.recipient && (
                    <span className="text-[10px] text-muted">→ {ev.recipient}</span>
                  )}
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300/70 font-bold uppercase tracking-wider">
                    {ev.type}
                  </span>
                  <span className="ml-auto text-[10px] text-muted/40 font-mono">{ev.time}</span>
                </div>
                <p className="text-sm text-white/90 whitespace-pre-wrap leading-relaxed">
                  {renderWithMentions(ev.content)}
                </p>
              </div>
            ))
          : visible.map(ev => {
              const style = typeStyles[ev.type] || defaultStyle;
              return (
                <div key={ev.id} className={`border-l-2 ${style.border} pl-3 py-2 group`}>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${style.badge}`}>
                      {style.badgeText}
                    </span>
                    <span className="flex-1 text-sm">
                      {CHAT_TYPES.has(ev.type) ? renderWithMentions(ev.content) : ev.content}
                    </span>
                    <span className="text-xs text-muted/40 font-mono">{ev.time}</span>
                  </div>
                </div>
              );
            })}
      </div>
      )}
    </div>
  );
}
