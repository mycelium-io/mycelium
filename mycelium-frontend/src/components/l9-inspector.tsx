// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchEpisode,
  fetchEpisodes,
  getSSEUrl,
  logFetchError,
  type EpisodeDetail,
  type EpisodeMetrics,
  type EpisodeSummary,
  type L9Envelope,
} from "@/lib/api";

// The L9 protocol inspector renders the AOP layer legibly: the live L9 payloads
// crossing a room's channel (exchange ticks/replies, commit verdicts with
// MPC/GAR/SCR, knowledge pushes) as a wire feed, plus the persisted episode
// records, the causal chain the broadcast envelopes deliberately omit.

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
  intent: "var(--muted)",
  contingency: "var(--yellow)",
};

function kindTone(kind: string): string {
  return KIND_TONE[kind] ?? "var(--muted)";
}

export function KindBadge({ kind, subkind }: { kind: string; subkind?: string | null }) {
  const tone = kindTone(kind);
  return (
    <span className="caps-mono-sm flex-shrink-0" style={{ color: tone }}>
      {kind.toUpperCase()}
      {subkind ? <span className="text-muted">:{subkind}</span> : null}
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
        <span key={label} title={title} className="text-text2">
          <span className="text-muted">{label}</span> {Number(value).toFixed(2)}
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
      <span className="font-mono text-label text-text2 truncate">{frame.sender}</span>
      <span className="text-text2 truncate">{frame.summary}</span>
      {frame.metrics ? <MetricsRow metrics={frame.metrics} /> : null}
      {frame.parents.length > 0 ? (
        <span className="text-micro text-muted font-mono" title={frame.parents.join("\n")}>
          ←{frame.parents.length}
        </span>
      ) : null}
      <span className="ml-auto text-micro text-muted font-mono tabular flex-shrink-0">{frame.time}</span>
    </div>
  );
}

/** One envelope in an episode's causal chain (parents come from the record). */
function EnvelopeRow({ env }: { env: L9Envelope }) {
  const header = env.header;
  const message = header.message ?? { id: "" };
  const actors = header.participants?.actors ?? [];
  const sender = actors[0]?.id ?? "?";
  const recipients = actors.slice(1).map((a) => a.id);
  const metrics = env.payload?.data?.metrics as EpisodeMetrics | undefined;
  return (
    <div className="flex items-baseline gap-2 px-4 py-1.5 border-b border-border last:border-b-0 text-body">
      <KindBadge kind={header.kind} subkind={header.subkind} />
      <span className="font-mono text-micro text-muted" title={message.id}>
        {message.id.slice(0, 6)}
      </span>
      <span className="font-mono text-label text-text2 truncate">{sender}</span>
      {recipients.length > 0 ? (
        <span className="caps-mono-sm text-muted truncate">→ {recipients.join(", ")}</span>
      ) : null}
      {metrics ? <MetricsRow metrics={metrics} /> : null}
      {message.parents && message.parents.length > 0 ? (
        <span
          className="ml-auto text-micro text-muted font-mono flex-shrink-0"
          title={message.parents.join("\n")}
        >
          ← {message.parents.map((p) => p.slice(0, 6)).join(" ")}
        </span>
      ) : (
        <span className="ml-auto text-micro text-muted font-mono flex-shrink-0">root</span>
      )}
    </div>
  );
}

/** An expandable episode card: summary → full causal chain on demand. */
function EpisodeCard({ roomName, episode }: { roomName: string; episode: EpisodeSummary }) {
  const [detail, setDetail] = useState<EpisodeDetail | null>(null);
  const [open, setOpen] = useState(false);
  const tone = episode.subkind === "rejected" ? "var(--yellow)" : "var(--green)";

  const toggle = useCallback(() => {
    setOpen((prev) => !prev);
    if (!detail) {
      fetchEpisode(roomName, episode.short_id)
        .then((d) => d && setDetail(d))
        .catch(logFetchError("fetchEpisode"));
    }
  }, [detail, roomName, episode.short_id]);

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        onClick={toggle}
        className="flex w-full items-baseline gap-2 px-4 py-2 text-left hover:bg-surface transition-colors"
      >
        <span className="caps-mono-sm flex-shrink-0" style={{ color: tone }}>
          {(episode.subkind ?? episode.outcome).toUpperCase()}
        </span>
        <span className="font-mono text-micro text-accent" title={episode.episode}>
          {episode.short_id}
        </span>
        <span className="text-text2 truncate">{episode.participants.join(", ")}</span>
        {episode.metrics ? <MetricsRow metrics={episode.metrics} /> : null}
        {episode.plan_file ? (
          <span className="font-mono text-micro text-muted truncate">→ {episode.plan_file}</span>
        ) : null}
        <span className="ml-auto text-micro text-muted font-mono flex-shrink-0">
          {episode.message_count} msg
        </span>
      </button>
      {open ? (
        <div className="bg-paper">
          {detail ? (
            detail.messages.map((env, i) => <EnvelopeRow key={env.header.message?.id ?? i} env={env} />)
          ) : (
            <div className="px-4 py-2 caps-mono-sm text-muted italic">loading chain…</div>
          )}
        </div>
      ) : null}
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
  const [episodes, setEpisodes] = useState<EpisodeSummary[]>([]);
  const [connected, setConnected] = useState(false);
  const wireRef = useRef<HTMLDivElement>(null);

  const loadEpisodes = useCallback(() => {
    fetchEpisodes(roomName)
      .then(setEpisodes)
      .catch(logFetchError("fetchEpisodes"));
  }, [roomName]);

  useEffect(() => {
    loadEpisodes();
  }, [loadEpisodes]);

  // Live L9 wire: same EventSource pattern as the room feed.
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
          // A commit means an episode record just closed. Refresh the list so
          // its causal chain becomes browsable.
          if (frame.kind === "commit") loadEpisodes();
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
  }, [roomName, loadEpisodes]);

  useEffect(() => {
    wireRef.current?.scrollTo({ top: wireRef.current.scrollHeight, behavior: "smooth" });
  }, [frames]);

  const wire = useMemo(() => frames, [frames]);

  return (
    <div className="flex flex-col h-full" data-testid="l9-inspector">
      <div className="flex items-center gap-2 px-4 border-b border-border shrink-0 h-[44px] bg-paper">
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            background: connected ? "var(--green)" : "var(--yellow)",
            animation: connected ? "myc-pulse 2s ease-in-out infinite" : undefined,
          }}
        />
        <span className="caps-mono-sm" style={{ color: connected ? "var(--green)" : "var(--yellow)" }}>
          {connected ? "L9 LIVE" : "RECONNECTING"}
        </span>
        <span className="ml-auto caps-mono-sm text-muted">L9 PROTOCOL</span>
      </div>

      <div ref={wireRef} className="flex-1 overflow-y-auto min-h-0">
        {wire.length === 0 ? (
          <div className="text-center caps-mono-sm text-muted py-10 italic">no L9 traffic yet</div>
        ) : (
          wire.map((frame) => <FrameRow key={frame.id} frame={frame} />)
        )}
      </div>

      <div className="border-t border-border shrink-0 max-h-[45%] overflow-y-auto bg-paper">
        <div className="px-4 py-2 caps-mono-sm text-muted sticky top-0 bg-paper border-b border-border">
          EPISODES · {episodes.length}
        </div>
        {episodes.length === 0 ? (
          <div className="text-center caps-mono-sm text-muted py-6 italic">no closed episodes</div>
        ) : (
          episodes.map((ep) => <EpisodeCard key={ep.short_id} roomName={roomName} episode={ep} />)
        )}
      </div>
    </div>
  );
}
