// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchMessages,
  fetchPendingInvites,
  respondToInvite,
  logFetchError,
  type PendingInvite,
} from "@/lib/api";
import { useRoomAgents } from "@/lib/room-data";
import { useRoomConnected, useRoomStream } from "@/lib/stream-hub";
import { MarkdownContent } from "@/components/markdown-content";
import { RoomBoard } from "@/components/board/room-board";
import { ConsentDialog } from "@/components/consent-dialog";
import { EpisodeTag } from "@/components/episode-tag";
import { L9Inspector } from "@/components/l9-inspector";
import { NegotiationView } from "@/components/negotiation-view";
import { RoomA2aView } from "@/components/room-a2a";
import { RoomSlimView } from "@/components/room-slim";
import { EmptyState } from "@/components/empty-state";
import { KeyBadge } from "@/components/key-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { ArrowDown, Bot, MessagesSquare } from "lucide-react";

interface Event {
  /** Render key only — synthesized, so a message republished by a status
   *  transition can't collide with the row it updates. */
  id: string;
  /** The backend's id for this message, where it has one. Stable across reads
   *  (the transcript derives it from the envelope id), which is what a search
   *  result points at. */
  messageId: string | null;
  type: string;
  content: string;
  sender: string;
  recipient: string | null;
  time: string;
  // The L9 episode URN this event belongs to, when it rode one. Negotiation
  // turns share their mediator's episode; casual chat carries the room default
  // or none. Lets the feed group/fold one negotiation's turns together.
  episode: string | null;
  /** The id of the message this one revises, when it is an amendment. The feed
   *  folds it into that message rather than showing it as a row of its own. */
  amends: string | null;
  /** True once an amendment has revised this message's text. */
  edited: boolean;
  raw: Record<string, unknown>;
}

const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

// The L9 "raise-up" whitelist: message types promoted from the L9 inspector
// into the primary channel/chat surface. This must mirror
// contracts/l9-surface.json's `raise_up_types` byte-for-byte — the CLI
// (mycelium-cli/src/mycelium/commands/room.py) carries an independent copy,
// and event-stream.contract.test.ts asserts both stay in sync with the
// contract so the two surfaces can't silently drift apart.
export const L9_RAISE_UP_TYPES = [
  "coordination_join",
  "coordination_consensus",
  "plan_updated",
  "l9_knowledge",
];

// Event types that appear in the chat-channel view alongside real chat.
// Joins + consensus belong here so the room's chat surface narrates the
// negotiation lifecycle ("alice joined session X", "CONSENSUS in session X
// → plan/tasks.md", "TIMEOUT in session X, no agreement") instead of
// burying it all under the EVENTS tab.
const CHANNEL_VIEW_TYPES = new Set([...CHAT_TYPES, ...L9_RAISE_UP_TYPES]);

// Lifecycle events that render as slim system notices (not chat rows). Used to
// decide message grouping: a chat message only groups under the sender above it
// when no system notice interrupts the run.
const SYSTEM_TYPES = new Set(L9_RAISE_UP_TYPES);

/** Skeleton loader for chat rows. */
function ChannelSkeleton() {
  const widths = ["w-3/5", "w-2/5", "w-1/2"];
  return (
    <div className="flex flex-col gap-5 px-5 py-4">
      {widths.map((w, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="size-8 flex-shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 pt-0.5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className={`mt-2 h-3 ${w}`} />
          </div>
        </div>
      ))}
    </div>
  );
}

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
    <div className="group mt-3 flex items-center gap-2 px-5 py-1 text-micro text-muted-foreground first:mt-0">
      <span aria-hidden className="inline-block size-1.5 flex-shrink-0 rounded-full" style={{ background: dot }} />
      {label && (
        <span className={strong ? "font-semibold" : "font-medium"} style={{ color: labelColor ?? "var(--muted-foreground)" }}>
          {label}
        </span>
      )}
      <span className="flex min-w-0 items-center gap-1.5 truncate">{children}</span>
      <span className="ml-auto flex-shrink-0 tabular text-faint opacity-0 transition-opacity group-hover:opacity-100">
        {time.slice(0, 5)}
      </span>
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
    case "l9_commit": {
      // Unwrap the L9 commit envelope into the coordination_consensus shape
      // so NegotiationView can render it.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const header = (l9env.header as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      const message = header.message as Record<string, unknown> | undefined;
      content = (raw.content as string) || "";
      raw = {
        ...raw,
        broken: header.subkind !== "converged",
        assignments: data.assignments,
        metrics: data.metrics,
        episode: message?.episode,
      };
      mtype = "coordination_consensus";
      break;
    }
    case "l9_knowledge": {
      // A memory push (e.g. the compiled plan syncing to every member) rides as
      // an L9 "knowledge" envelope. Recognized as its own system notice rather
      // than falling to the unhandled-type fallback.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      content = (raw.content as string) || `${(data.key as string) ?? "memory"} updated`;
      raw = { ...raw, key: data.key, updated_by: data.updated_by, version: data.version };
      break;
    }
    default:
      // A message type nothing above handles would otherwise vanish from the
      // channel view without a trace (exactly how l9_exchange hid). Surface it
      // loudly so an unsupported/renamed type can't fail silently again.
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

  // An amendment names the message it revises: over SSE that's the L9 envelope's
  // subkind + parents, on the REST snapshot the backend has already folded it and
  // only the `edited_at` stamp survives.
  const l9header = ((raw.l9 as Record<string, unknown> | undefined)?.header ??
    {}) as Record<string, unknown>;
  const parents = (l9header.message as Record<string, unknown> | undefined)?.parents;
  const amends =
    l9header.subkind === "amend" && Array.isArray(parents) && typeof parents[0] === "string"
      ? (parents[0] as string)
      : typeof msg.amends === "string"
        ? msg.amends
        : null;

  return {
    id: `${Date.now()}-${Math.random()}`,
    messageId: typeof msg.id === "string" ? msg.id : null,
    type: mtype,
    content,
    sender,
    recipient,
    time,
    episode,
    amends,
    edited: typeof msg.edited_at === "string",
    raw,
  };
}

/** A reader a couple of lines off the bottom still counts as reading the tail,
 *  so a stray wheel tick doesn't detach them. */
const PIN_TOLERANCE_PX = 64;

/** Fold an amendment into the message it revises, or keep it as its own row.
 *
 *  The backend folds a cold read; the live stream carries the amendment as the
 *  message it is, so the open tab has to fold it too or it reads as the sender
 *  repeating themselves. An amendment that matches nothing here (its target
 *  scrolled out of this window, or came from someone else) stays visible rather
 *  than being dropped — the same rule the read path follows. */
function foldAmendment(events: Event[], amendment: Event): Event[] {
  const target = events.findIndex(
    (e) =>
      e.messageId === amendment.amends &&
      e.sender === amendment.sender &&
      e.amends === null,
  );
  if (target === -1) return [...events, amendment];
  return events.map((e, i) =>
    i === target ? { ...e, content: amendment.content, edited: true } : e,
  );
}

export type View = "channel" | "negotiate" | "plan" | "network";
export type NegotiationPhase = "idle" | "negotiating" | "converged" | "rejected";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
  onConnectionChange?: (connected: boolean) => void;
  onNegotiationPhaseChange?: (phase: NegotiationPhase) => void;
  /** Open a memory by key — wired to `[[wikilinks]]` in chat so a message can
   *  link a room's memory and a reader (or agent author) can jump straight to it. */
  onOpenMemory?: (key: string) => void;
  /** Open an episode by short id — wired to the episode tags on coordination
   *  notices, so the episode a notice names is one click from its record. */
  onOpenEpisode?: (shortId: string) => void;
  /** Optional controlled tab (e.g. driven by the onboarding tour). */
  view?: View;
  onViewChange?: (view: View) => void;
  /** Hold back the consent-request modal (e.g. during the onboarding tour, so
   *  its backdrop doesn't cover the coached highlights). */
  suppressInvites?: boolean;
  /** A message to reveal in the channel, arrived at from search. */
  focusMessageId?: string | null;
  onFocusConsumed?: () => void;
}

export function EventStream({ roomName, onMemoryChanged, onConnectionChange, onNegotiationPhaseChange, onOpenMemory, onOpenEpisode, view: viewProp, onViewChange, suppressInvites = false, focusMessageId = null, onFocusConsumed }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const connected = useRoomConnected(roomName);

  // Surface connection state to status bar; one home for the signal.
  useEffect(() => {
    onConnectionChange?.(connected);
  }, [connected, onConnectionChange]);
  const [viewInternal, setViewInternal] = useState<View>("channel");
  const view = viewProp ?? viewInternal;
  const setView = (v: View) => { if (viewProp === undefined) setViewInternal(v); onViewChange?.(v); };
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Know which senders are registered agents (to badge their replies) and whom
  // each belongs to (to attribute them inline). Off the room's shared agent
  // read, so this costs no request of its own; owner is resolved at render time
  // so it always reflects the current manifest, never a stale stamp.
  const { agents } = useRoomAgents(roomName);
  const agentHandles = useMemo(() => new Set(agents.map((a) => a.handle)), [agents]);
  const agentOwners = useMemo(
    () => new Map(agents.filter((a) => a.owner).map((a) => [a.handle, a.owner as string])),
    [agents],
  );

  // Load initial messages
  useEffect(() => {
    fetchMessages(roomName).then(data => {
      const msgs = (data.messages || []).reverse();
      setEvents(msgs.map(parseEvent));
      setHistoryLoaded(true);
    }).catch((err) => {
      logFetchError("fetchMessages")(err);
      setHistoryLoaded(true);
    });
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

  // Live room messages, off the app's one multiplexed connection.
  useRoomStream(roomName, (data) => {
    const msg = data as Record<string, unknown>;
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
    setEvents(prev => (event.amends ? foldAmendment(prev, event) : [...prev, event]));
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
  });

  const visible = useMemo(
    () => events.filter(e => CHANNEL_VIEW_TYPES.has(e.type)),
    [events],
  );

  // Arriving from search: mark the named message and scroll it into sight once
  // history has landed. The mark outlives the request that carried it — a
  // highlight cleared with the URL parameter would be gone before it was read.
  const [highlight, setHighlight] = useState<string | null>(null);
  const highlightRow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusMessageId) return;
    // The highlight outlives focusMessageId, which is cleared once consumed.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHighlight(focusMessageId);
    onFocusConsumed?.();
  }, [focusMessageId, onFocusConsumed]);

  // The feed follows new messages only while the reader is on the tail; scroll
  // up and it holds still. A jump-back button carries the count of what landed
  // meanwhile, so leaving the tail doesn't read as a quiet room.
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  // visible.length at the moment the reader left the tail.
  const [detachedAt, setDetachedAt] = useState(0);
  const visibleCount = useRef(0);

  useEffect(() => {
    // Only the channel renders this viewport; the other views replace it, so
    // the ref is null for them and the pin is left as they found it.
    const el = scrollRef.current;
    if (!el) return;
    // A view switch unmounts the viewport, and a remount starts at the top;
    // put a pinned reader back on the tail rather than in the archive.
    if (atBottomRef.current) el.scrollTop = el.scrollHeight;
    const measure = () => {
      const pinned = el.scrollHeight - el.scrollTop - el.clientHeight <= PIN_TOLERANCE_PX;
      if (pinned === atBottomRef.current) return;
      atBottomRef.current = pinned;
      if (!pinned) setDetachedAt(visibleCount.current);
      setAtBottom(pinned);
    };
    el.addEventListener("scroll", measure, { passive: true });
    return () => el.removeEventListener("scroll", measure);
  }, [view]);

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = true;
    setAtBottom(true);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const unread = atBottom ? 0 : Math.max(0, visible.length - detachedAt);

  // Auto-scroll when new events arrive — but not over a message the user was
  // just sent to, which is the one place in the feed they're looking, and not
  // over history they scrolled up to read.
  useEffect(() => {
    visibleCount.current = visible.length;
    if (highlight || !atBottomRef.current) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visible, highlight]);

  useEffect(() => {
    if (!highlight) return;
    highlightRow.current?.scrollIntoView({ block: "center" });
  }, [highlight, historyLoaded, visible]);

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
        {/* Connection state lives in the shell status bar. */}
        <div className="ml-auto flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {([
            { id: "channel" as const,   label: "Channel",   count: channelCount as number | null, dot: false },
            { id: "negotiate" as const, label: "Negotiate", count: null,                          dot: negotiating },
            { id: "plan" as const,      label: "Board",     count: null,                          dot: false },
            { id: "network" as const,   label: "Network",   count: null,                          dot: false },
          ]).map(t => {
            // Hold the reveal modifier and each tab wears the key that selects it.
            const active = view === t.id;
            return (
              <button
                key={t.id}
                data-tour={`tab-${t.id}`}
                onClick={() => setView(t.id)}
                className={`relative flex items-center gap-1.5 rounded-md px-3 py-1 text-label font-medium transition-colors ${
                  active
                    ? "bg-elevated text-text shadow-sm ring-1 ring-border"
                    : "text-muted-foreground hover:bg-hairline hover:text-text"
                }`}
              >
                {t.label}
                <KeyBadge action={`pane.${t.id}`} />
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
      {view === "plan" ? (
        <div className="flex-1 min-h-0">
          <RoomBoard roomName={roomName} />
        </div>
      ) : view === "network" ? (
        // Unified Network pane: SLIM channel diagnostics as a rail on top, the
        // A2A bridge (the room's off-channel traffic) beneath it when there is
        // one, and the live L9 protocol feed filling the rest.
        <div className="flex flex-1 min-h-0 flex-col">
          <div className="shrink-0 border-b border-border bg-surface/40">
            <RoomSlimView roomName={roomName} layout="rail" />
          </div>
          <div className="shrink-0">
            <RoomA2aView roomName={roomName} />
          </div>
          <div className="flex-1 min-h-0">
            <L9Inspector roomName={roomName} />
          </div>
        </div>
      ) : view === "negotiate" ? (
        <div className="flex-1 min-h-0">
          <NegotiationView events={events} />
        </div>
      ) : (
      <div className="relative flex flex-1 min-h-0 flex-col">
      <ScrollArea className="flex-1 min-h-0" viewportRef={scrollRef}>
        {!historyLoaded ? (
          <ChannelSkeleton />
        ) : visible.length === 0 ? (
          <EmptyState
            className="h-full"
            icon={MessagesSquare}
            title="No messages yet"
            description="Post a position or @-mention an agent to get the room talking."
          />
        ) : (
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
              if (ev.type === "l9_knowledge") {
                const key = ev.raw.key as string | undefined;
                const updatedBy = ev.raw.updated_by as string | undefined;
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--yellow)" label="Knowledge">
                    <span>{ev.content}</span>
                    {key && <span className="font-mono text-muted-foreground">{key}</span>}
                    {updatedBy ? <span>by @{updatedBy}</span> : null}
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
                      <EpisodeTag urn={episodeUrn} shortId={shortId} onOpen={onOpenEpisode} />
                    ) : (
                      <span className="font-mono">episode</span>
                    )}
                    {broken ? (
                      <span>· no agreement</span>
                    ) : (
                      <>
                        <span>· {issueCount} issue{issueCount === 1 ? "" : "s"} agreed</span>
                        {gar !== undefined ? (
                          <Tooltip content="Genuine agreement ratio: how many agents actually moved toward the outcome">
                            <span
                              className="font-mono"
                              aria-description="Genuine agreement ratio: how many agents actually moved toward the outcome"
                            >
                              · GAR {gar.toFixed(2)}
                            </span>
                          </Tooltip>
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
                      <EpisodeTag urn={episodeUrn} shortId={shortId} onOpen={onOpenEpisode} />
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
              // Match the members panel so one sender isn't two colours in two
              // places: an agent wears its own stable tint (Monogram's default),
              // a human the neutral seat.
              const color = isAgent ? undefined : "var(--avatar-neutral)";
              const marked = highlight !== null && ev.messageId === highlight;
              const owner = isAgent ? agentOwners.get(ev.sender) : undefined;
              return (
                <div
                  key={ev.id}
                  ref={marked ? highlightRow : undefined}
                  className={`group relative flex gap-3 px-5 hover:bg-hairline ${grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0"} ${
                    marked ? "bg-accent/15" : ""
                  }`}
                >
                  {/* Timestamp low-signal: right gutter, hover-revealed. */}
                  <span className="pointer-events-none absolute right-5 top-1.5 text-micro tabular text-faint opacity-0 transition-opacity group-hover:opacity-100">
                    {ev.time.slice(0, 5)}
                  </span>

                  <div className="w-7 flex-shrink-0">
                    {!grouped && (
                      <Tooltip content={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
                        <span role="img" aria-label={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
                          <Monogram handle={ev.sender} color={color} className="size-7 text-micro" />
                        </span>
                      </Tooltip>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    {!grouped && (
                      <div className="flex items-center gap-1.5 pr-12">
                        <span className="text-label font-semibold text-text truncate">
                          {ev.sender}
                        </span>
                        {isAgent && (
                          <Bot aria-label="agent" className="size-3 flex-shrink-0 text-accent" />
                        )}
                        {ev.recipient && (
                          <span className="rounded bg-hairline px-1.5 py-px font-mono text-micro text-muted-foreground">
                            → {ev.recipient}
                          </span>
                        )}
                      </div>
                    )}
                    <MarkdownContent className="contrast text-body leading-relaxed" onLinkClick={onOpenMemory}>
                      {ev.content}
                    </MarkdownContent>
                    {ev.edited && (
                      <span className="text-micro text-faint" title="revised by a later message">
                        (edited)
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
        </div>
        )}
      </ScrollArea>
      {!atBottom && visible.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
          <Button
            size="sm"
            variant="secondary"
            onClick={jumpToLatest}
            aria-label={unread > 0 ? `Jump to latest, ${unread} new` : "Jump to latest"}
            className="pointer-events-auto rounded-full border-border bg-elevated shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1"
          >
            <ArrowDown className="size-3.5" />
            {unread > 0 ? `${unread} new ${unread === 1 ? "message" : "messages"}` : "Jump to latest"}
          </Button>
        </div>
      )}
      </div>
      )}
    </div>
  );
}
