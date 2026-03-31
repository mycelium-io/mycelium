// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useRef, useState } from "react";
import { getSSEUrl, fetchMessages } from "@/lib/api";

interface Event {
  id: string;
  type: string;
  content: string;
  sender: string;
  time: string;
  raw: Record<string, unknown>;
}

function parseEvent(msg: Record<string, unknown>): Event {
  const mtype = (msg.message_type as string) || (msg.type as string) || "unknown";
  const sender = (msg.sender_handle as string) || (msg.updated_by as string) || "?";
  const created = (msg.created_at as string) || new Date().toISOString();
  const time = created.slice(11, 19);

  let content = "";
  let raw: Record<string, unknown> = {};

  try {
    if (typeof msg.content === "string") {
      raw = JSON.parse(msg.content);
    } else if (msg.content) {
      raw = msg.content as Record<string, unknown>;
    } else {
      raw = msg;
    }
  } catch {
    raw = msg;
  }

  switch (mtype) {
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
      const round = raw.round || "?";
      const action = raw.action || "tick";
      const participant = raw.participant_id || "?";
      content = `Round ${round}: ${participant} → ${action}`;
      if (raw.current_offer) content += ` ${JSON.stringify(raw.current_offer)}`;
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

  return { id: `${Date.now()}-${Math.random()}`, type: mtype, content, sender, time, raw };
}

const typeStyles: Record<string, { border: string; badge: string; badgeText: string }> = {
  coordination_join:      { border: "border-l-cyan-400",    badge: "bg-cyan-500/10 text-cyan-400",    badgeText: "join" },
  coordination_start:     { border: "border-l-cyan-400",    badge: "bg-cyan-500/15 text-cyan-300",    badgeText: "start" },
  coordination_tick:      { border: "border-l-indigo-400",  badge: "bg-indigo-500/10 text-indigo-400", badgeText: "tick" },
  coordination_consensus: { border: "border-l-emerald-400", badge: "bg-emerald-500/10 text-emerald-400", badgeText: "consensus" },
  memory_changed:         { border: "border-l-yellow-400",  badge: "bg-yellow-500/10 text-yellow-400", badgeText: "memory" },
  synthesis_complete:     { border: "border-l-emerald-400", badge: "bg-emerald-500/10 text-emerald-400", badgeText: "synthesis" },
};

const defaultStyle = { border: "border-l-muted", badge: "bg-muted/10 text-muted", badgeText: "msg" };

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
}

export function EventStream({ roomName, onMemoryChanged }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

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

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
        <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
        <span className="text-xs text-muted font-mono">{connected ? "connected" : "reconnecting..."}</span>
        <span className="ml-auto text-xs text-muted/50">{events.length} events</span>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {events.length === 0 && (
          <div className="text-center text-muted/50 py-20 text-sm">Waiting for events...</div>
        )}
        {events.map(ev => {
          const style = typeStyles[ev.type] || defaultStyle;
          return (
            <div key={ev.id} className={`border-l-2 ${style.border} pl-3 py-2 group`}>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${style.badge}`}>
                  {style.badgeText}
                </span>
                <span className="flex-1 text-sm">{ev.content}</span>
                <span className="text-xs text-muted/40 font-mono">{ev.time}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
