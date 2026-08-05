// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  getSSEUrl,
  fetchMessages,
  fetchRoomAgents,
  fetchPendingInvites,
  respondToInvite,
  logFetchError,
  type PendingInvite,
} from "@/lib/api";
import { MarkdownContent } from "@/components/markdown-content";
import { RoomPlanHeader } from "@/components/room-plan-header";
import { ConsentDialog } from "@/components/consent-dialog";

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
// Event types that appear in the chat-channel view alongside real chat.
// Joins + consensus belong here so the room's chat surface narrates the
// negotiation lifecycle — "alice joined session X", "CONSENSUS in session X
// → plan/tasks.md", "TIMEOUT in session X — no agreement" — instead of
// burying it all under the EVENTS tab.
const CHANNEL_VIEW_TYPES = new Set([
  ...CHAT_TYPES,
  "coordination_join",
  "coordination_consensus",
  "plan_updated",
]);

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
      {
        const metrics = raw.metrics as Record<string, unknown> | undefined;
        const gar = metrics && typeof metrics === "object" ? metrics.gar : undefined;
        if (typeof gar === "number" && Number.isFinite(gar)) content += ` · GAR ${gar.toFixed(2)}`;
      }
      break;
    }
    case "memory_changed": {
      const key = (raw.key || msg.key) as string;
      const version = (raw.version || msg.version) as number;
      const by = (raw.updated_by || msg.updated_by) as string;
      content = `${key} v${version} by ${by}`;
      break;
    }
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

type View = "channel" | "plan";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
  planRefreshTrigger?: number;
}

export function EventStream({ roomName, onMemoryChanged, planRefreshTrigger = 0 }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);
  const [view, setView] = useState<View>("channel");
  const [agentHandles, setAgentHandles] = useState<Set<string>>(new Set());
  const [invites, setInvites] = useState<PendingInvite[]>([]);
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
        .catch(logFetchError("fetchRoomAgents"));
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
    }).catch(logFetchError("fetchMessages"));
  }, [roomName]);

  // Load any consent prompts already open (an @-invite raised before this
  // client connected). Live ones arrive over SSE below.
  useEffect(() => {
    fetchPendingInvites(roomName)
      .then((open) => setInvites(open.filter((i) => i.status === "pending")))
      .catch(logFetchError("fetchPendingInvites"));
  }, [roomName]);

  const respond = (invite: PendingInvite, decision: "accept" | "decline") => {
    setInvites((prev) => prev.filter((i) => i.id !== invite.id));
    respondToInvite(roomName, invite.id, decision).catch(logFetchError("respondToInvite"));
  };

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
          // Consent prompts drive the accept/decline dialog, not the feed.
          if (msg.message_type === "consent_request") {
            try {
              const invite = JSON.parse(msg.content as string) as PendingInvite;
              setInvites((prev) =>
                prev.some((i) => i.id === invite.id) ? prev : [...prev, invite],
              );
            } catch {}
            return;
          }
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
    () => events.filter(e => CHANNEL_VIEW_TYPES.has(e.type)),
    [events],
  );

  // Auto-scroll when new events arrive
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visible]);

  const channelCount = useMemo(
    () => events.filter(e => CHANNEL_VIEW_TYPES.has(e.type)).length,
    [events],
  );

  return (
    <div className="flex flex-col h-full">
      <ConsentDialog
        invite={invites[0] ?? null}
        onAccept={(invite) => respond(invite, "accept")}
        onDecline={(invite) => respond(invite, "decline")}
      />
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
            { id: "channel" as const, label: "CHANNEL", count: channelCount as number | null },
            { id: "plan" as const,    label: "PLAN",    count: null },
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
                {t.count !== null && (
                  <span className="text-micro tabular" style={{ color: active ? "var(--accent)" : "var(--muted)" }}>
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {view === "plan" ? (
          <RoomPlanHeader roomName={roomName} refreshTrigger={planRefreshTrigger} />
        ) : (
          <>
        {visible.length === 0 && (
          <div className="text-center caps-mono-sm text-muted py-16 italic">
            no channel messages yet
          </div>
        )}
        {visible.map(ev => {
              // Coordination + plan lifecycle events render as slim system
              // notices (NOT chat-bubble rows): a JOIN line per agent join,
              // a CONSENSUS / TIMEOUT line when a session resolves, and a
              // PLAN line per plan edit (title set, task add, task toggle).
              // Each links out where appropriate.
              if (ev.type === "plan_updated") {
                const kind = ev.raw.kind as string | undefined;
                const text = ev.raw.text as string | undefined;
                const title = ev.raw.title as string | undefined;
                const done = ev.raw.done === true;
                const updatedBy = ev.raw.updated_by as string | undefined;
                let body: React.ReactNode;
                if (kind === "task_toggled") {
                  body = (
                    <>
                      <span style={{ color: done ? "var(--green)" : "var(--muted)" }}>
                        {done ? "✓" : "○"}
                      </span>
                      <span className="text-text2 truncate">
                        &ldquo;{text ?? "task"}&rdquo;
                      </span>
                      <span className="text-muted">
                        {done ? "completed" : "reopened"}
                      </span>
                    </>
                  );
                } else if (kind === "task_added") {
                  body = (
                    <>
                      <span className="text-muted">added</span>
                      <span className="text-text2 truncate">
                        &ldquo;{text ?? "task"}&rdquo;
                      </span>
                    </>
                  );
                } else if (kind === "title_set") {
                  body = (
                    <>
                      <span className="text-muted">title set to</span>
                      <span className="text-text2 truncate">
                        &ldquo;{title ?? ""}&rdquo;
                      </span>
                      {updatedBy ? (
                        <span className="text-muted">by @{updatedBy}</span>
                      ) : null}
                    </>
                  );
                } else {
                  body = <span className="text-text2">updated</span>;
                }
                return (
                  <div
                    key={ev.id}
                    className="flex items-baseline gap-2 px-5 py-2 border-b border-border last:border-b-0 text-body italic text-text2"
                  >
                    <span className="caps-mono-sm flex-shrink-0" style={{ color: "var(--accent)" }}>
                      PLAN
                    </span>
                    {body}
                    <span className="ml-auto text-micro text-muted font-mono tabular flex-shrink-0">
                      {ev.time}
                    </span>
                  </div>
                );
              }
              if (ev.type === "coordination_consensus") {
                const broken = ev.raw.broken === true;
                const session = ev.raw.session as string | undefined;
                const shortId = session ? session.split(":").pop() : undefined;
                const sessionHref = shortId
                  ? `/room/${encodeURIComponent(roomName)}/session/${encodeURIComponent(shortId)}`
                  : null;
                const planFile = ev.raw.plan_file as string | undefined;
                const assignments = ev.raw.assignments as Record<string, string> | undefined;
                const issueCount = assignments ? Object.keys(assignments).length : 0;
                const metrics = ev.raw.metrics && typeof ev.raw.metrics === "object"
                  ? (ev.raw.metrics as Record<string, unknown>)
                  : undefined;
                const garRaw = metrics ? metrics.gar : undefined;
                const gar = typeof garRaw === "number" && Number.isFinite(garRaw) ? garRaw : undefined;
                const label = broken ? "TIMEOUT" : "CONSENSUS";
                const tone = broken ? "var(--yellow)" : "var(--green)";
                return (
                  <div
                    key={ev.id}
                    className="flex items-baseline gap-2 px-5 py-2 border-b border-border last:border-b-0 text-body italic text-text2"
                  >
                    <span className="caps-mono-sm flex-shrink-0" style={{ color: tone }}>
                      {label}
                    </span>
                    <span className="text-muted">in</span>
                    {sessionHref ? (
                      <Link
                        href={sessionHref}
                        className="font-mono text-accent hover:underline"
                      >
                        {shortId}
                      </Link>
                    ) : (
                      <span className="font-mono text-text2">session</span>
                    )}
                    {broken ? (
                      <span className="text-text2">— no agreement</span>
                    ) : (
                      <>
                        <span className="text-muted">·</span>
                        <span className="text-text2">
                          {issueCount} issue{issueCount === 1 ? "" : "s"} agreed
                        </span>
                        {gar !== undefined ? (
                          <>
                            <span className="text-muted">·</span>
                            <span
                              className="font-mono text-text2"
                              title="genuine agreement ratio: how many agents actually moved toward the outcome"
                            >
                              GAR {gar.toFixed(2)}
                            </span>
                          </>
                        ) : null}
                        {planFile ? (
                          <>
                            <span className="text-muted">→</span>
                            <span className="font-mono text-accent">{planFile}</span>
                          </>
                        ) : null}
                      </>
                    )}
                    <span className="ml-auto text-micro text-muted font-mono tabular flex-shrink-0">
                      {ev.time}
                    </span>
                  </div>
                );
              }
              if (ev.type === "coordination_join") {
                const handle = (ev.raw.handle as string | undefined) ?? ev.sender;
                const intent = (ev.raw.intent as string | undefined) ?? "";
                const session = ev.raw.session as string | undefined;
                const shortId = session ? session.split(":").pop() : undefined;
                const sessionHref = shortId
                  ? `/room/${encodeURIComponent(roomName)}/session/${encodeURIComponent(shortId)}`
                  : null;
                return (
                  <div
                    key={ev.id}
                    className="flex items-baseline gap-2 px-5 py-2 border-b border-border last:border-b-0 text-body italic text-text2"
                  >
                    <span className="caps-mono-sm flex-shrink-0" style={{ color: "var(--muted)" }}>
                      JOIN
                    </span>
                    <span className="font-mono font-semibold" style={{ color: "var(--green)" }}>
                      @{handle}
                    </span>
                    <span className="text-muted">joined</span>
                    {sessionHref ? (
                      <Link
                        href={sessionHref}
                        className="font-mono text-accent hover:underline"
                      >
                        {shortId}
                      </Link>
                    ) : null}
                    {intent ? (
                      <span className="text-text2 truncate">— &ldquo;{intent}&rdquo;</span>
                    ) : null}
                    <span className="ml-auto text-micro text-muted font-mono tabular flex-shrink-0">
                      {ev.time}
                    </span>
                  </div>
                );
              }
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
            })}
          </>
        )}
      </div>
    </div>
  );
}
