// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getSSEUrl, fetchMessages, fetchRoomAgents } from "@/lib/api";
import { MarkdownContent } from "@/components/markdown-content";

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
      const planFile = raw.plan_file as string | undefined;
      const broken = raw.broken === true;
      const assignments = raw.assignments as Record<string, string>;
      content = plan || "";
      if (assignments) content += " " + Object.entries(assignments).map(([k, v]) => `${k}=${v}`).join(", ");
      // Consensus isn't the end — it compiles into the room's shared plan.
      if (!broken && planFile) content += ` · compiled → ${planFile}`;
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

// Per-event-type styling. Tone drives the accent color of the label + bar.
const typeStyles: Record<string, { tone: "accent" | "ok" | "warn" | "muted" | "ink"; label: string }> = {
  broadcast:              { tone: "ink",    label: "BROADCAST" },
  direct:                 { tone: "accent", label: "DIRECT" },
  announce:               { tone: "ink",    label: "ANNOUNCE" },
  delegate:               { tone: "accent", label: "DELEGATE" },
  coordination_join:      { tone: "accent", label: "JOIN" },
  coordination_start:     { tone: "accent", label: "START" },
  coordination_tick:      { tone: "muted",  label: "TICK" },
  coordination_consensus: { tone: "ok",     label: "CONSENSUS" },
  memory_changed:         { tone: "warn",   label: "MEMORY" },
  synthesis_complete:     { tone: "ok",     label: "SYNTHESIS" },
};
const defaultStyle = { tone: "muted" as const, label: "MSG" };

function toneColor(t: "accent" | "ok" | "warn" | "muted" | "ink"): string {
  return t === "accent" ? "var(--accent)"
       : t === "ok"     ? "var(--green)"
       : t === "warn"   ? "var(--yellow)"
       : t === "ink"    ? "var(--text)"
                        : "var(--muted)";
}

/** Two-letter monogram for a chat avatar (mirrors AgentsPanel). */
function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2
      ? parts[0][0] + parts[1][0]
      : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

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

type View = "channel" | "events";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
}

export function EventStream({ roomName, onMemoryChanged }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);
  const [view, setView] = useState<View>("channel");
  const [agentHandles, setAgentHandles] = useState<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  // Know which senders are registered agents so their replies can be badged.
  // Self-fetched (mirrors the chat box) so the page doesn't have to thread it.
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchRoomAgents(roomName)
        .then((a) => {
          if (!cancelled) setAgentHandles(new Set(a.map((x) => x.handle)));
        })
        .catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
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
          // A consensus compiles the negotiation into plan/tasks.md — nudge
          // the plan header to refetch so the checklist surfaces immediately.
          if (event.type === "coordination_consensus" && event.raw.broken !== true) {
            onMemoryChanged?.();
          }
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
      <div className="flex items-stretch border-b border-border shrink-0 h-[44px] bg-paper">
        <div className="flex items-center gap-2 px-4">
          <span
            aria-hidden
            style={{
              width: 6, height: 6,
              background: connected ? "var(--green)" : "var(--yellow)",
              animation: connected ? "myc-pulse 2s ease-in-out infinite" : undefined,
            }}
          />
          <span className="caps-mono-sm" style={{ color: connected ? "var(--green)" : "var(--yellow)" }}>
            {connected ? "LIVE" : "RECONNECTING"}
          </span>
        </div>
        <div className="ml-auto flex items-stretch">
          {([
            { id: "channel" as const, label: "CHANNEL", count: channelCount },
            { id: "events" as const,  label: "EVENTS",  count: events.length },
          ]).map(t => {
            const active = view === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setView(t.id)}
                className={`flex items-center gap-2 px-4 caps-mono-sm border-l border-border transition-colors ${
                  active ? "text-accent" : "text-text2 hover:text-text"
                }`}
                style={{ borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}` }}
              >
                {t.label}
                <span className="text-micro tabular" style={{ color: active ? "var(--accent)" : "var(--muted)" }}>
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {visible.length === 0 && (
          <div className="text-center caps-mono-sm text-muted py-16 italic">
            {view === "channel" ? "no channel messages yet" : "waiting for events…"}
          </div>
        )}
        {view === "channel"
          ? visible.map(ev => {
              const isAgent = agentHandles.has(ev.sender);
              const color = isAgent ? "var(--green)" : "var(--accent)";
              return (
                <div
                  key={ev.id}
                  className="flex gap-3 px-5 py-3 border-b border-border last:border-b-0"
                >
                  <div
                    className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-surface font-mono text-micro font-bold mt-0.5"
                    style={{ border: `1.5px solid ${color}`, color }}
                    aria-hidden
                  >
                    {initials(ev.sender)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2 mb-1">
                      <span
                        className="font-mono text-label font-semibold truncate"
                        style={{ color }}
                      >
                        {ev.sender}
                      </span>
                      {isAgent && (
                        <span
                          className="caps-mono-sm flex-shrink-0"
                          style={{ color: "var(--green)" }}
                        >
                          AGENT
                        </span>
                      )}
                      {ev.recipient && (
                        <span className="caps-mono-sm text-muted">
                          → {ev.recipient}
                        </span>
                      )}
                      <span className="ml-auto text-micro text-muted font-mono tabular">
                        {ev.time}
                      </span>
                    </div>
                    <MarkdownContent className="text-body text-text2 leading-relaxed">
                      {ev.content}
                    </MarkdownContent>
                  </div>
                </div>
              );
            })
          : visible.map(ev => {
              const style = typeStyles[ev.type] || defaultStyle;
              const color = toneColor(style.tone);
              return (
                <div
                  key={ev.id}
                  className="px-5 py-2 border-b border-border hover:bg-white/[0.02]"
                  style={{ borderLeft: `2px solid ${color}` }}
                >
                  <div className="flex items-baseline gap-3">
                    <span className="caps-mono-sm flex-shrink-0" style={{ color, minWidth: 90 }}>
                      {style.label}
                    </span>
                    <span className="flex-1 text-body text-text2 leading-snug min-w-0 break-words">
                      {CHAT_TYPES.has(ev.type) ? renderWithMentions(ev.content) : ev.content}
                    </span>
                    <span className="text-micro text-muted font-mono tabular flex-shrink-0">{ev.time}</span>
                  </div>
                </div>
              );
            })}
      </div>
    </div>
  );
}
