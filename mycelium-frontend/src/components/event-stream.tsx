// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

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
import { L9Inspector } from "@/components/l9-inspector";
import { NegotiationView } from "@/components/negotiation-view";
import { RoomSlimView } from "@/components/room-slim";
import { EmptyState } from "@/components/empty-state";
import { initials } from "@/components/ui/monogram";
import { MessagesSquare } from "lucide-react";

interface Event {
  id: string;
  type: string;
  content: string;
  sender: string;
  recipient: string | null;
  time: string;
  // The L9 episode URN this event belongs to, when it rode one. Negotiation
  // turns share their mediator's episode; casual chat carries the room default
  // or none. Lets the feed group/fold one negotiation's turns together.
  episode: string | null;
  raw: Record<string, unknown>;
}

const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);
// Event types that appear in the chat-channel view alongside real chat.
// Joins + consensus belong here so the room's chat surface narrates the
// negotiation lifecycle ("alice joined session X", "CONSENSUS in session X
// → plan/tasks.md", "TIMEOUT in session X, no agreement") instead of
// burying it all under the EVENTS tab.
const CHANNEL_VIEW_TYPES = new Set([
  ...CHAT_TYPES,
  "coordination_join",
  "coordination_consensus",
  "plan_updated",
]);

// Lifecycle events that render as slim system notices (not chat rows). Used to
// decide message grouping: a chat message only groups under the sender above it
// when no system notice interrupts the run.
const SYSTEM_TYPES = new Set([
  "coordination_join",
  "coordination_consensus",
  "plan_updated",
]);

/** A quiet, centered lifecycle line woven into the conversation. */
function SystemNotice({
  time,
  dot,
  label,
  labelColor,
  strong,
  children,
}: {
  time: string;
  dot: string;
  label?: string;
  labelColor?: string;
  strong?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 px-5 py-1.5 text-micro text-muted-foreground">
      <span aria-hidden className="inline-block size-1.5 flex-shrink-0 rounded-full" style={{ background: dot }} />
      {label && (
        <span className={strong ? "font-semibold" : "font-medium"} style={{ color: labelColor ?? "var(--muted-foreground)" }}>
          {label}
        </span>
      )}
      <span className="flex min-w-0 items-center gap-1.5 truncate">{children}</span>
      <span className="ml-auto flex-shrink-0 tabular">{time}</span>
    </div>
  );
}

function parseEvent(msg: Record<string, unknown>): Event {
  let mtype = (msg.message_type as string) || (msg.type as string) || "unknown";
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
      content = `${handle} joined${intent ? `: ${intent}` : ""}`;
      break;
    }
    case "coordination_start":
      content = `Episode started with ${raw.agent_count || "?"} agents`;
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
      // Consensus isn't the end; it compiles into the room's shared plan.
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
    case "l9_exchange":
      // The live SSE stream wraps human/agent messages as an L9 exchange
      // envelope, while the REST snapshot (loaded on mount/refresh) delivers the
      // same message as a plain "broadcast". Unwrap the prose and normalise to
      // the chat shape so the live feed matches a refresh instead of silently
      // dropping the message.
      content = (raw.content as string) || "";
      mtype = recipient ? "direct" : "broadcast";
      break;
    default:
      // A message type nothing above handles would otherwise vanish from the
      // channel view without a trace (exactly how l9_exchange hid). Surface it
      // loudly so an unsupported/renamed type can't fail silently again.
      // eslint-disable-next-line no-console
      console.warn(
        `[mycelium] EventStream: unhandled message_type "${mtype}" — ` +
          "rendered as a raw fallback and likely hidden from the channel view",
        msg,
      );
      content = (msg.content as string) || JSON.stringify(msg).slice(0, 100);
  }

  const episode =
    (msg.episode as string) ||
    ((raw.header as Record<string, unknown> | undefined)?.message as
      | Record<string, unknown>
      | undefined)?.episode as string ||
    null;

  return {
    id: `${Date.now()}-${Math.random()}`,
    type: mtype,
    content,
    sender,
    recipient,
    time,
    episode,
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
  coordination_leave:     { tone: "muted",  label: "LEAVE" },
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
                        : "var(--muted-foreground)";
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

export type View = "channel" | "negotiate" | "plan" | "l9" | "slim";
export type NegotiationPhase = "idle" | "negotiating" | "converged" | "rejected";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
  onConnectionChange?: (connected: boolean) => void;
  onNegotiationPhaseChange?: (phase: NegotiationPhase) => void;
  planRefreshTrigger?: number;
  /** Optional controlled tab (e.g. driven by the onboarding tour). */
  view?: View;
  onViewChange?: (view: View) => void;
  /** Hold back the consent-request modal (e.g. during the onboarding tour, so
   *  its backdrop doesn't cover the coached highlights). */
  suppressInvites?: boolean;
}

export function EventStream({ roomName, onMemoryChanged, onConnectionChange, onNegotiationPhaseChange, planRefreshTrigger = 0, view: viewProp, onViewChange, suppressInvites = false }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [connected, setConnected] = useState(false);

  // Surface connection state to the shell's status bar (editor-style), so the
  // chat header stays clean and the live/reconnecting signal has one home.
  useEffect(() => {
    onConnectionChange?.(connected);
  }, [connected, onConnectionChange]);
  const [viewInternal, setViewInternal] = useState<View>("channel");
  const view = viewProp ?? viewInternal;
  const setView = (v: View) => { if (viewProp === undefined) setViewInternal(v); onViewChange?.(v); };
  const [agentHandles, setAgentHandles] = useState<Set<string>>(new Set());
  const [agentOwners, setAgentOwners] = useState<Map<string, string>>(new Map());
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Know which senders are registered agents (to badge their replies) and whom
  // each belongs to (to attribute them inline). Self-fetched (mirrors the chat
  // box) so the page doesn't have to thread it; owner is resolved at render time
  // so it always reflects the current manifest, never a stale stamp.
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchRoomAgents(roomName)
        .then((a) => {
          if (cancelled) return;
          setAgentHandles(new Set(a.map((x) => x.handle)));
          setAgentOwners(
            new Map(a.filter((x) => x.owner).map((x) => [x.handle, x.owner as string])),
          );
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
          // A consensus compiles the negotiation into plan/tasks.md, so nudge
          // the plan header to refetch so the checklist surfaces immediately.
          if (event.type === "coordination_consensus" && event.raw.broken !== true) {
            onMemoryChanged?.();
          }
          // Presence changes: refresh the room's derived state (agent roster/count).
          if (event.type === "coordination_join" || event.type === "coordination_leave") {
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

  // Negotiation phase, derived from the coordination stream. Drives the live
  // tab dot and (via the callback) the onboarding tour's convergence sync.
  const phase = useMemo<NegotiationPhase>(() => {
    let lastTick = -1;
    let lastConsensus = -1;
    let consensusBroken = false;
    events.forEach((e, i) => {
      if (e.type === "coordination_tick") lastTick = i;
      if (e.type === "coordination_consensus") {
        lastConsensus = i;
        consensusBroken = e.raw.broken === true;
      }
    });
    if (lastConsensus > -1 && lastConsensus > lastTick) return consensusBroken ? "rejected" : "converged";
    if (lastTick > -1) return "negotiating";
    return "idle";
  }, [events]);
  const negotiating = phase === "negotiating";

  useEffect(() => {
    onNegotiationPhaseChange?.(phase);
  }, [phase, onNegotiationPhaseChange]);

  return (
    <div className="flex flex-col h-full">
      <ConsentDialog
        invite={suppressInvites ? null : (invites[0] ?? null)}
        onAccept={(invite) => respond(invite, "accept")}
        onDecline={(invite) => respond(invite, "decline")}
      />
      <div className="flex items-center gap-3 border-b border-border shrink-0 h-[48px] bg-paper px-4">
        {/* Connection state lives in the shell status bar now, not here. */}
        <div className="ml-auto flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {([
            { id: "channel" as const,   label: "Channel",   count: channelCount as number | null, dot: false },
            { id: "negotiate" as const, label: "Negotiate", count: null,                          dot: negotiating },
            { id: "l9" as const,        label: "L9",        count: null,                          dot: false },
            { id: "plan" as const,      label: "Plan",      count: null,                          dot: false },
            { id: "slim" as const,      label: "SLIM",      count: null,                          dot: false },
          ]).map(t => {
            const active = view === t.id;
            return (
              <button
                key={t.id}
                data-tour={`tab-${t.id}`}
                onClick={() => setView(t.id)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-label font-medium transition-colors ${
                  active
                    ? "bg-elevated text-text shadow-sm ring-1 ring-border"
                    : "text-muted-foreground hover:bg-hairline hover:text-text"
                }`}
              >
                {t.label}
                {t.dot && <span className="inline-block size-1.5 rounded-full bg-accent" aria-label="live" />}
                {t.count !== null && (
                  <span className={`text-micro tabular ${active ? "text-accent" : "text-muted-foreground"}`}>
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      {view === "l9" ? (
        <div className="flex-1 min-h-0">
          <L9Inspector roomName={roomName} />
        </div>
      ) : view === "negotiate" ? (
        <div className="flex-1 min-h-0">
          <NegotiationView events={events} />
        </div>
      ) : view === "slim" ? (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <RoomSlimView roomName={roomName} />
        </div>
      ) : (
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {view === "plan" ? (
          <RoomPlanHeader roomName={roomName} refreshTrigger={planRefreshTrigger} />
        ) : (
          <>
        {visible.length === 0 && (
          <EmptyState
            icon={MessagesSquare}
            title="No messages yet"
            description="Post a position or @-mention an agent to get the room talking."
          />
        )}
        <div className="py-3">
        {visible.map((ev, idx) => {
              // Coordination + plan lifecycle events render as slim, centered
              // system notices — quiet dividers woven into the conversation,
              // not loud rows. Chat messages group under one sender header.
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
                      <span style={{ color: done ? "var(--green)" : "var(--muted-foreground)" }}>
                        {done ? "✓" : "○"}
                      </span>
                      <span className="text-muted-foreground">&ldquo;{text ?? "task"}&rdquo;</span>
                      <span>{done ? "completed" : "reopened"}</span>
                    </>
                  );
                } else if (kind === "task_added") {
                  body = (
                    <>
                      <span>added</span>
                      <span className="text-muted-foreground">&ldquo;{text ?? "task"}&rdquo;</span>
                    </>
                  );
                } else if (kind === "title_set") {
                  body = (
                    <>
                      <span>title set to</span>
                      <span className="text-muted-foreground">&ldquo;{title ?? ""}&rdquo;</span>
                      {updatedBy ? <span>by @{updatedBy}</span> : null}
                    </>
                  );
                } else {
                  body = <span>updated</span>;
                }
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--accent)" label="Plan">
                    {body}
                  </SystemNotice>
                );
              }
              if (ev.type === "coordination_consensus") {
                const broken = ev.raw.broken === true;
                const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
                const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
                const planFile = ev.raw.plan_file as string | undefined;
                const assignments = ev.raw.assignments as Record<string, string> | undefined;
                const issueCount = assignments ? Object.keys(assignments).length : 0;
                const metrics = ev.raw.metrics && typeof ev.raw.metrics === "object"
                  ? (ev.raw.metrics as Record<string, unknown>)
                  : undefined;
                const garRaw = metrics ? metrics.gar : undefined;
                const gar = typeof garRaw === "number" && Number.isFinite(garRaw) ? garRaw : undefined;
                const tone = broken ? "var(--yellow)" : "var(--green)";
                return (
                  <SystemNotice
                    key={ev.id}
                    time={ev.time}
                    dot={tone}
                    label={broken ? "Timeout" : "Consensus"}
                    labelColor={tone}
                    strong
                  >
                    <span>in</span>
                    {shortId ? (
                      <span className="font-mono text-accent" title={episodeUrn}>{shortId}</span>
                    ) : (
                      <span className="font-mono">episode</span>
                    )}
                    {broken ? (
                      <span>· no agreement</span>
                    ) : (
                      <>
                        <span>· {issueCount} issue{issueCount === 1 ? "" : "s"} agreed</span>
                        {gar !== undefined ? (
                          <span className="font-mono" title="genuine agreement ratio: how many agents actually moved toward the outcome">
                            · GAR {gar.toFixed(2)}
                          </span>
                        ) : null}
                        {planFile ? (
                          <span>→ <span className="font-mono text-accent">{planFile}</span></span>
                        ) : null}
                      </>
                    )}
                  </SystemNotice>
                );
              }
              if (ev.type === "coordination_join") {
                const handle = (ev.raw.handle as string | undefined) ?? ev.sender;
                const intent = (ev.raw.intent as string | undefined) ?? "";
                const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
                const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--muted-foreground)">
                    <span className="font-medium text-muted-foreground">@{handle}</span>
                    <span>joined</span>
                    {shortId ? (
                      <span className="font-mono text-accent" title={episodeUrn}>{shortId}</span>
                    ) : null}
                    {intent ? <span>· &ldquo;{intent}&rdquo;</span> : null}
                  </SystemNotice>
                );
              }
              // A chat message groups with the one above it when the same
              // sender speaks consecutively (no intervening system notice).
              const prev = visible[idx - 1];
              const grouped =
                prev &&
                !SYSTEM_TYPES.has(prev.type) &&
                prev.sender === ev.sender;
              const isAgent = agentHandles.has(ev.sender);
              // Agents wear the accent; humans stay neutral. Consistent with the
              // agents panel so one agent isn't two colors in two places.
              const color = isAgent ? "var(--accent)" : "var(--muted-foreground)";
              return (
                <div
                  key={ev.id}
                  className={`group flex gap-3 px-5 hover:bg-hairline ${grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0"}`}
                >
                  <div className="w-8 flex-shrink-0">
                    {grouped ? (
                      <span className="block pt-1 text-right text-micro tabular text-muted-foreground opacity-0 group-hover:opacity-100">
                        {ev.time.slice(0, 5)}
                      </span>
                    ) : (
                      <div
                        className="flex size-8 items-center justify-center rounded-full text-micro font-semibold"
                        style={{ background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}
                        aria-hidden
                      >
                        {initials(ev.sender)}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    {!grouped && (
                      <div className="flex items-baseline gap-2">
                        <span className="text-label font-semibold text-text truncate">
                          {ev.sender}
                        </span>
                        {isAgent && (
                          <span
                            className="rounded px-1.5 py-px text-micro font-medium"
                            style={{ color: "var(--accent)", background: "color-mix(in srgb, var(--accent) 14%, transparent)" }}
                          >
                            agent
                          </span>
                        )}
                        {isAgent && agentOwners.get(ev.sender) && (
                          <span className="text-micro text-muted-foreground truncate">
                            owned by @{agentOwners.get(ev.sender)}
                          </span>
                        )}
                        {ev.recipient && (
                          <span className="text-micro text-muted-foreground">→ {ev.recipient}</span>
                        )}
                        <span className="text-micro text-muted-foreground tabular">{ev.time}</span>
                      </div>
                    )}
                    <MarkdownContent className="contrast text-body leading-relaxed">
                      {ev.content}
                    </MarkdownContent>
                  </div>
                </div>
              );
            })}
        </div>
          </>
        )}
      </div>
      )}
    </div>
  );
}
