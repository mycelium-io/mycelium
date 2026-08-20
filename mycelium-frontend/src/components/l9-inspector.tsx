// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowLeftRight,
  BookOpen,
  ChevronRight,
  Circle,
  CircleCheck,
  CircleX,
  Radio,
  Target,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchL9History,
  getSSEUrl,
  logFetchError,
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
  /** The wire message this frame was projected from, kept for the expanded view. */
  raw: Record<string, unknown>;
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
    raw: msg,
  };
}

/**
 * Pretty-print a frame's wire message. The bus transports the envelope as a
 * JSON string under `content`; decode it so headers, payload, and parents read
 * as structure rather than one escaped string.
 */
export function envelopeJson(raw: Record<string, unknown>): string {
  let display = raw;
  if (typeof raw.content === "string") {
    try {
      display = { ...raw, content: JSON.parse(raw.content) };
    } catch {
      /* non-JSON content stays a string */
    }
  }
  return JSON.stringify(display, null, 2);
}

// One pass over pretty-printed JSON: quoted strings (key when a colon follows,
// else value), literals, and numbers. Punctuation/whitespace fall between matches.
const JSON_TOKENS = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

/** JSON syntax highlight: colors keys, strings, numbers, literals. */
export function highlightJson(src: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of src.matchAll(JSON_TOKENS)) {
    const start = m.index ?? 0;
    if (start > last) out.push(src.slice(last, start));
    const [full, str, colon, lit, num] = m;
    if (str !== undefined) {
      out.push(
        colon ? (
          <span key={key++} className="text-accent">{str}</span>
        ) : (
          <span key={key++} style={{ color: "var(--green)" }}>{str}</span>
        ),
      );
      if (colon) out.push(colon);
    } else if (lit !== undefined) {
      out.push(<span key={key++} className="text-red">{lit}</span>);
    } else if (num !== undefined) {
      out.push(<span key={key++} className="text-yellow">{num}</span>);
    }
    last = start + full.length;
  }
  if (last < src.length) out.push(src.slice(last));
  return out;
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

/** Row tone, refined by subkind: a rejected commit reads red, not the green of a
 *  converged one. Everything else follows its kind. */
function frameTone(kind: string, subkind?: string | null): string {
  if (kind === "commit") return subkind === "rejected" ? "var(--red)" : "var(--green)";
  return kindTone(kind);
}

/** One glyph per kind — the scannable anchor at the start of every row. Commit
 *  splits on outcome (✓ converged/resolved, ✕ rejected). */
function frameIcon(kind: string, subkind?: string | null): LucideIcon {
  switch (kind) {
    case "exchange":
      return ArrowLeftRight;
    case "commit":
      return subkind === "rejected" ? CircleX : CircleCheck;
    case "knowledge":
      return BookOpen;
    case "contingency":
      return TriangleAlert;
    case "intent":
      return Target;
    default:
      return Circle;
  }
}

export function KindBadge({ kind, subkind }: { kind: string; subkind?: string | null }) {
  return (
    <span
      className="block min-w-0 truncate font-mono text-label font-semibold uppercase tracking-[0.02em]"
      style={{ color: frameTone(kind, subkind) }}
      title={`${kind}${subkind ? ":" + subkind : ""}`}
    >
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

/** One live wire frame; click toggles the full envelope JSON below the summary. */
function FrameRow({
  frame,
  onExpandedChange,
}: {
  frame: L9Frame;
  onExpandedChange: (delta: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  // Report expansion to the inspector (which pauses auto-scroll while any row
  // is open); the cleanup un-reports when the row collapses or scrolls out of
  // the frame cap.
  useEffect(() => {
    if (!expanded) return;
    onExpandedChange(1);
    return () => onExpandedChange(-1);
  }, [expanded, onExpandedChange]);

  const Icon = frameIcon(frame.kind, frame.subkind);
  const tone = frameTone(frame.kind, frame.subkind);

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        title={expanded ? "Collapse envelope" : "Expand full envelope JSON"}
        // Fixed columns so kind / actor / summary line up down the feed, one text
        // size throughout; timestamp + metrics ride a right-aligned meta cluster.
        className="group grid w-full cursor-pointer grid-cols-[14px_16px_176px_120px_minmax(0,1fr)_auto] items-center gap-x-2.5 px-4 py-1.5 text-left text-label transition-colors hover:bg-hairline"
      >
        <ChevronRight
          aria-hidden
          className={`size-3.5 text-faint transition-transform group-hover:text-muted-foreground ${expanded ? "rotate-90" : ""}`}
        />
        <Icon aria-hidden className="size-3.5" style={{ color: tone }} />
        <KindBadge kind={frame.kind} subkind={frame.subkind} />
        <span className="truncate font-mono text-muted-foreground">{frame.sender}</span>
        <span className="min-w-0 truncate text-text">{frame.summary}</span>
        <span className="flex items-center justify-end gap-2.5 text-micro text-muted-foreground">
          {frame.metrics ? <MetricsRow metrics={frame.metrics} /> : null}
          {frame.parents.length > 0 ? (
            <span className="font-mono tabular" title={frame.parents.join("\n")}>
              ←{frame.parents.length}
            </span>
          ) : null}
          {frame.episode ? (
            <span className="font-mono text-accent" title={frame.episode}>
              {shortEpisode(frame.episode)}
            </span>
          ) : null}
          <span className="font-mono tabular">{frame.time}</span>
        </span>
      </button>
      {expanded ? (
        <ScrollArea className="mx-4 mb-2 h-64 border border-border bg-surface">
          <pre
            data-testid="frame-json"
            className="px-2.5 py-2 font-mono text-micro text-muted-foreground whitespace-pre-wrap break-words"
          >
            {highlightJson(envelopeJson(frame.raw))}
          </pre>
        </ScrollArea>
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
  const [connected, setConnected] = useState(false);
  // Kinds toggled off; empty by default so new kinds auto-show.
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const [episodeFilter, setEpisodeFilter] = useState<string>("all");
  const wireRef = useRef<HTMLDivElement>(null);
  // Frame ids already shown, so a history-backfill row and its live re-push don't
  // double up. Reset per room.
  const seenIds = useRef<Set<string>>(new Set());
  // How many rows are currently expanded; while > 0 the feed stops following
  // the tail so incoming frames don't yank an open envelope out of view.
  const expandedRows = useRef(0);
  const onExpandedChange = useCallback((delta: number) => {
    expandedRows.current += delta;
  }, []);

  // History backfill: the transcript replayed through the same frame shape, so a
  // freshly opened tab isn't empty (the SSE bus below carries no history). Runs
  // per room, before/alongside the live stream; the shared seenIds set dedups a
  // backfilled row against any live re-push.
  useEffect(() => {
    let cancelled = false;
    seenIds.current = new Set();
    setFrames([]);
    fetchL9History(roomName).then((rows) => {
      if (cancelled) return;
      const seeded: L9Frame[] = [];
      for (const row of rows) {
        const frame = toL9Frame(row);
        if (frame && !seenIds.current.has(frame.id)) {
          seenIds.current.add(frame.id);
          seeded.push(frame);
        }
      }
      // Prepend history ahead of any live frames that arrived during the fetch.
      setFrames((prev) => [...seeded, ...prev].slice(-MAX_FRAMES));
    }).catch(logFetchError("fetchL9History"));
    return () => { cancelled = true; };
  }, [roomName]);

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
          if (!frame || seenIds.current.has(frame.id)) return;
          seenIds.current.add(frame.id);
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

  // Kinds + episodes actually present in the feed so far, for the filter controls.
  const kindsPresent = useMemo(
    () => Array.from(new Set(frames.map((f) => f.kind))).sort(),
    [frames],
  );
  const episodesPresent = useMemo(
    () => Array.from(new Set(frames.map((f) => f.episode).filter((e): e is string => Boolean(e)))),
    [frames],
  );
  // Reset filters that no longer apply to any frame (e.g. the selected episode
  // scrolled out of the MAX_FRAMES window).
  useEffect(() => {
    if (episodeFilter !== "all" && !episodesPresent.includes(episodeFilter)) {
      setEpisodeFilter("all");
    }
  }, [episodeFilter, episodesPresent]);

  const toggleKind = useCallback((kind: string) => {
    setHiddenKinds((prev) => {
      const next = new Set(prev);
      next.has(kind) ? next.delete(kind) : next.add(kind);
      return next;
    });
  }, []);

  const wire = useMemo(
    () =>
      frames.filter(
        (f) => !hiddenKinds.has(f.kind) && (episodeFilter === "all" || f.episode === episodeFilter),
      ),
    [frames, hiddenKinds, episodeFilter],
  );

  useEffect(() => {
    if (expandedRows.current > 0) return;
    wireRef.current?.scrollTo({ top: wireRef.current.scrollHeight, behavior: "smooth" });
  }, [wire]);

  const filtered = frames.length > 0 && wire.length === 0;

  return (
    <div className="flex flex-col h-full" data-testid="l9-inspector">
      {/* No title bar; pane tab already reads "Network". */}
      {!connected && (
        <div className="flex items-center gap-1.5 px-4 shrink-0 h-[28px] border-b border-border bg-paper caps-mono-sm text-yellow">
          <span aria-hidden className="inline-block size-1.5 rounded-full bg-yellow" />
          RECONNECTING
        </div>
      )}

      {frames.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border shrink-0 bg-paper">
          <span className="caps-mono-sm text-muted-foreground">L9 PROTOCOL</span>
          <span className="h-3 w-px bg-border" aria-hidden />
          <div className="flex flex-wrap items-center gap-1">
            {kindsPresent.map((kind) => {
              const active = !hiddenKinds.has(kind);
              return (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={active}
                  aria-label={`Toggle ${kind} frames`}
                  onClick={() => toggleKind(kind)}
                  className={`flex items-center gap-1.5 rounded-md px-2 py-1 caps-mono-sm transition-colors ${
                    active
                      ? "bg-elevated text-text shadow-sm ring-1 ring-border"
                      : "text-muted-foreground hover:bg-hairline hover:text-text"
                  }`}
                >
                  <span
                    aria-hidden
                    className="inline-block size-1.5 rounded-full"
                    style={{ background: active ? kindTone(kind) : "var(--muted-foreground)" }}
                  />
                  {/* Lowercase; caps-mono-sm uppercases visually. */}
                  {kind}
                </button>
              );
            })}
          </div>
          {episodesPresent.length > 0 && (
            <select
              aria-label="Filter by episode"
              value={episodeFilter}
              onChange={(e) => setEpisodeFilter(e.target.value)}
              className="ml-auto rounded-md border border-border bg-surface px-2 py-1 font-mono text-micro text-muted-foreground focus:border-accent focus:text-text focus:outline-none"
            >
              <option value="all">All episodes</option>
              {episodesPresent.map((ep) => (
                <option key={ep} value={ep}>
                  {shortEpisode(ep)}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <ScrollArea className="flex-1 min-h-0" viewportRef={wireRef}>
        {wire.length === 0 ? (
          <EmptyState
            className="h-full"
            icon={Radio}
            title={filtered ? "No frames match the current filters" : "No L9 traffic yet"}
            description={
              filtered
                ? "Try clearing a kind toggle or switching episodes."
                : "Protocol envelopes stream here as agents coordinate: exchanges, commits, and knowledge."
            }
          />
        ) : (
          wire.map((frame) => (
            <FrameRow key={frame.id} frame={frame} onExpandedChange={onExpandedChange} />
          ))
        )}
      </ScrollArea>
    </div>
  );
}
