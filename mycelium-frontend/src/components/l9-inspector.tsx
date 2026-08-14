// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Radio } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import {
  getSSEUrl,
  type EpisodeMetrics,
  type L9Envelope,
} from "@/lib/api";

// The L9 protocol inspector renders the AOP layer legibly: the live L9 payloads
// crossing a room's channel (exchange ticks/replies, commit verdicts with
// MPC/GAR/SCR, knowledge pushes) as a wire feed, plus the persisted episode
// records and their causal chain.

// ── frame model ────────────────────────────────────────────────────────────────

export interface L9Frame {
  id: string;
  kind: string; // exchange | commit | knowledge | intent | contingency
  subkind: string | null;
  episode: string | null;
  parents: string[];
  sender: string;
  summary: string;
  metrics: EpisodeMetrics | null;
  time: string;
}

/** Short, human episode id: the trailing `:session` segment of the URN. */
export function shortEpisode(urn: string | null | undefined): string {
  if (!urn) return "";
  const parts = urn.split(":");
  return parts[parts.length - 1] || urn;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function frameSummary(
  kind: string,
  content: Record<string, unknown>,
  data: Record<string, unknown>,
): string {
  switch (kind) {
    case "exchange": {
      const round = data.round ?? content.round;
      const action = data.action ?? content.action ?? "exchange";
      return round != null ? `round ${round} · ${action}` : String(action);
    }
    case "commit": {
      const assignments = asRecord(data.assignments ?? content.assignments);
      const pairs = Object.entries(assignments)
        .map(([k, v]) => `${k}=${v}`)
        .join(", ");
      return pairs || "consensus";
    }
    case "knowledge": {
      const key = data.key ?? content.key ?? content.slug ?? "knowledge push";
      return String(key);
    }
    case "intent":
      return String(data.intent ?? content.intent ?? "mission");
    default:
      return kind;
  }
}

/**
 * Project a room-bus message into an L9 wire frame, or null when the message
 * isn't protocol traffic (plain chat). Prefers the embedded `l9` envelope (the
 * source of truth); falls back to the message_type when a raw event carries no
 * envelope.
 */
export function toL9Frame(msg: Record<string, unknown>): L9Frame | null {
  const mtype = String(msg.message_type ?? msg.type ?? "");
  const created = String(msg.created_at ?? "");
  const time = created.length >= 19 ? created.slice(11, 19) : "";

  let content: Record<string, unknown> = {};
  if (typeof msg.content === "string") {
    try {
      content = JSON.parse(msg.content);
    } catch {
      content = {};
    }
  } else {
    content = asRecord(msg.content);
  }

  // The envelope may be embedded under `l9`, OR be the content itself (the
  // persister feeds the bus a bare `{header, payload}` envelope as `l9_<kind>`),
  // OR be absent (route-level events like memory_changed carry only fields).
  const embedded = content.l9 && typeof content.l9 === "object" ? (content.l9 as L9Envelope) : null;
  const bare = content.header && typeof content.header === "object" ? (content as unknown as L9Envelope) : null;
  const env = embedded ?? bare;
  const header = env?.header;
  // Sender: prefer the flat `sender_handle` the persister stamps on bus frames;
  // fall back to the envelope's first actor (the bus sender convention) so a
  // bare `{header, payload}` envelope still shows its handle instead of "?".
  const sender = String(msg.sender_handle ?? header?.participants?.actors?.[0]?.id ?? "?");
  // Payload data lives on the envelope; route-level events (coordination_tick)
  // nest their fields under `content.payload` instead.
  const data = env ? asRecord(env.payload?.data) : asRecord(content.payload);

  let kind = header?.kind ?? "";
  let subkind = header?.subkind ?? null;
  const episode = header?.message?.episode ?? (content.episode as string) ?? null;
  const parents = header?.message?.parents ?? [];

  if (!kind) {
    if (mtype.startsWith("l9_")) {
      kind = mtype.slice(3); // persister shape: l9_exchange / l9_commit / …
    } else if (mtype === "coordination_tick") {
      kind = "exchange";
    } else if (mtype === "coordination_consensus") {
      kind = "commit";
      subkind = content.broken === true ? "rejected" : "converged";
    } else if (mtype === "coordination_join" || mtype === "coordination_start") {
      kind = "intent";
    } else if (mtype === "knowledge" || mtype === "memory_changed" || mtype === "plan_updated") {
      kind = "knowledge";
    } else {
      return null; // plain chat, not inspector traffic
    }
  }

  let metrics: EpisodeMetrics | null = null;
  const rawMetrics = data.metrics ?? content.metrics;
  if (rawMetrics && typeof rawMetrics === "object") metrics = rawMetrics as EpisodeMetrics;

  const id = header?.message?.id ?? `${mtype}:${created}:${sender}:${Math.random()}`;

  return {
    id,
    kind,
    subkind,
    episode,
    parents,
    sender,
    summary: frameSummary(kind, content, data),
    metrics,
    time,
  };
}

// ── presentation ────────────────────────────────────────────────────────────────

const KIND_TONE: Record<string, string> = {
  exchange: "var(--accent)",
  commit: "var(--green)",
  knowledge: "var(--yellow)",
  intent: "var(--muted-foreground)",
  contingency: "var(--yellow)",
};

function kindTone(kind: string): string {
  return KIND_TONE[kind] ?? "var(--muted-foreground)";
}

export function KindBadge({ kind, subkind }: { kind: string; subkind?: string | null }) {
  const tone = kindTone(kind);
  return (
    <span className="caps-mono-sm flex-shrink-0" style={{ color: tone }}>
      {kind.toUpperCase()}
      {subkind ? <span className="text-muted-foreground">:{subkind}</span> : null}
    </span>
  );
}

export function MetricsRow({ metrics }: { metrics: EpisodeMetrics }) {
  const items: [string, number, string][] = [
    ["MPC", metrics.mpc, "mean posterior confidence"],
    ["GAR", metrics.gar, "genuine agreement ratio"],
    ["SCR", metrics.scr, "social compliance ratio"],
  ];
  return (
    <span className="flex items-center gap-2 font-mono text-micro tabular">
      {items.map(([label, value, title]) => (
        <span key={label} title={title} className="text-muted-foreground">
          <span className="text-muted-foreground">{label}</span> {Number(value).toFixed(2)}
        </span>
      ))}
    </span>
  );
}

/** One live wire frame. */
function FrameRow({ frame }: { frame: L9Frame }) {
  return (
    <div className="flex items-baseline gap-2 px-4 py-2 border-b border-border last:border-b-0 text-body">
      <KindBadge kind={frame.kind} subkind={frame.subkind} />
      {frame.episode ? (
        <span className="font-mono text-micro text-accent" title={frame.episode}>
          {shortEpisode(frame.episode)}
        </span>
      ) : null}
      <span className="font-mono text-label text-muted-foreground truncate">{frame.sender}</span>
      <span className="text-muted-foreground truncate">{frame.summary}</span>
      {frame.metrics ? <MetricsRow metrics={frame.metrics} /> : null}
      {frame.parents.length > 0 ? (
        <span className="text-micro text-muted-foreground font-mono" title={frame.parents.join("\n")}>
          ←{frame.parents.length}
        </span>
      ) : null}
      <span className="ml-auto text-micro text-muted-foreground font-mono tabular flex-shrink-0">{frame.time}</span>
    </div>
  );
}

// ── inspector ─────────────────────────────────────────────────────────────────

interface Props {
  roomName: string;
}

const MAX_FRAMES = 200;

export function L9Inspector({ roomName }: Props) {
  const [frames, setFrames] = useState<L9Frame[]>([]);
  const [connected, setConnected] = useState(false);
  const wireRef = useRef<HTMLDivElement>(null);

  // Live L9 wire: same EventSource pattern as the room feed. (Episodes have
  // their own home in the inspector's Episodes tab + review drawer; this tab is
  // purely the live protocol feed.)
  useEffect(() => {
    const url = getSSEUrl(roomName);
    let es: EventSource;
    let retry: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(url);
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          const frame = toL9Frame(msg);
          if (!frame) return;
          setFrames((prev) => [...prev, frame].slice(-MAX_FRAMES));
        } catch {
          /* ignore malformed frames */
        }
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        retry = setTimeout(connect, 5000);
      };
    }

    connect();
    return () => {
      es?.close();
      clearTimeout(retry);
    };
  }, [roomName]);

  useEffect(() => {
    wireRef.current?.scrollTo({ top: wireRef.current.scrollHeight, behavior: "smooth" });
  }, [frames]);

  const wire = useMemo(() => frames, [frames]);

  return (
    <div className="flex flex-col h-full" data-testid="l9-inspector">
      <div className="flex items-center gap-2 px-4 border-b border-border shrink-0 h-[48px] bg-paper">
        <span className="caps-mono-sm text-muted-foreground">L9 PROTOCOL</span>
        {!connected && (
          <span className="caps-mono-sm text-yellow flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-1.5 rounded-full bg-yellow" />
            RECONNECTING
          </span>
        )}
      </div>

      <div ref={wireRef} className="flex-1 overflow-y-auto min-h-0">
        {wire.length === 0 ? (
          <EmptyState
            className="h-full"
            icon={Radio}
            title="No L9 traffic yet"
            description="Protocol envelopes stream here as agents coordinate: exchanges, commits, and knowledge."
          />
        ) : (
          wire.map((frame) => <FrameRow key={frame.id} frame={frame} />)
        )}
      </div>
    </div>
  );
}
