// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The patterns explorer: pick a multi-agent pattern, run it, and watch the
 * team work through it in a room of its own.
 *
 * Three columns: the patterns, the attendants of the one open, and the run.
 * The run reads top to bottom as before → now, the flow the conductor walks,
 * and what the members said, with the person's turn in the composer when the
 * flow puts a question to them. What a pattern is and why it matters lives in
 * its guide rather than on the page.
 *
 * It is a client of the public API and nothing more: the hub loads a pattern
 * as a room (`/api/patterns/{name}/load`), runs it with the conductor, and
 * restates where it stands after every step (`context/standing`); this reads
 * the room the way the app's own room view does.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronsLeft, ChevronsRight, CircleHelp, ExternalLink, Play, RotateCcw } from "lucide-react";
import type { EpisodeFlow, EpisodeSummary, Room, RoomFloor, RoomMessage } from "@/lib/api";
import { ApiError, sendRoomMessage } from "@/lib/api";
import { conductorLineOf, isSuccess, type ConductorLine } from "@/lib/conductor-line";
import {
  STANDING_KEY,
  latestRoomOf,
  loadPattern,
  standingOf,
  usePattern,
  usePatterns,
  withStance,
  type PatternRead,
  type PatternSummary,
  type Standing,
} from "@/lib/patterns";
import {
  useRoomEpisodes,
  useRoomMembers,
  useRoomMemories,
  useRoomRevalidate,
  useRooms,
  useThreadMessages,
} from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { startGuide, type TourHandle } from "@/lib/tour";
import { useCurrentUser } from "@/components/current-user";
import { FlowGraph } from "@/components/flow-graph";
import { MessageBody } from "@/components/message-body";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** How often a run's reads refresh when the live stream is quiet. */
const LIVE_MS = 4_000;

const RAIL_KEY = "mycelium.patterns.rail";
const GUIDED_KEY = (name: string) => `mycelium.patterns.guided.${name}`;
const MARKER = /\[\[mycelium:[^\]]*\]\]/g;

function readFlag(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string, on: boolean): void {
  try {
    window.localStorage.setItem(key, on ? "1" : "0");
  } catch {
    // A convenience; the page works without it.
  }
}

function initialsOf(title: string): string {
  const words = title.split(/\s+/).filter((w) => /^[a-z]/i.test(w));
  return (words.length > 1 ? words[0][0] + words[1][0] : title.slice(0, 2)).toUpperCase();
}

function clock(stamp: string | undefined): string {
  if (!stamp) return "";
  const at = new Date(stamp);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Who plays what: the flow's roles bound to the summon's cast, in order. */
function rolesOf(pattern: PatternRead): Map<string, string> {
  const cast = pattern.scenario.summon?.members ?? [];
  const roles = new Map<string, string>();
  cast.forEach((handle, i) => {
    const role = pattern.roles[i];
    roles.set(handle, role ?? "worker");
  });
  return roles;
}

// ── the page ─────────────────────────────────────────────────────────────────

export function PatternExplorer({ name }: { name: string | null }) {
  const router = useRouter();
  const { patterns, error } = usePatterns();
  const current = name ?? patterns[0]?.pattern ?? null;
  const { pattern } = usePattern(current);
  const { rooms, refresh: refreshRooms } = useRooms({ refreshInterval: 10_000 });
  const room = current ? latestRoomOf(rooms, current) : null;

  const [collapsed, setCollapsed] = useState(() => readFlag(RAIL_KEY));
  const toggleRail = () => {
    setCollapsed((c) => {
      writeFlag(RAIL_KEY, !c);
      return !c;
    });
  };

  return (
    <div
      className="grid h-screen bg-bg text-text"
      style={{ gridTemplateColumns: `${collapsed ? 56 : 216}px 208px minmax(0,1fr)` }}
    >
      <PatternRail
        patterns={patterns}
        rooms={rooms}
        current={current}
        collapsed={collapsed}
        onToggle={toggleRail}
        onPick={(p) => router.push(`/patterns/${encodeURIComponent(p)}`)}
        error={error}
      />
      {pattern && room ? (
        <RunView key={room.name} pattern={pattern} room={room} onRan={refreshRooms} />
      ) : (
        <IdleView pattern={pattern} onRan={refreshRooms} />
      )}
    </div>
  );
}

// ── the patterns ─────────────────────────────────────────────────────────────

function PatternRail({
  patterns,
  rooms,
  current,
  collapsed,
  onToggle,
  onPick,
  error,
}: {
  patterns: PatternSummary[];
  rooms: Room[];
  current: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onPick: (pattern: string) => void;
  error?: Error;
}) {
  return (
    <nav className="flex min-h-0 flex-col border-r border-border">
      <div className={cn("flex h-12 shrink-0 items-center border-b border-border", collapsed ? "justify-center" : "gap-2 px-4")}>
        {!collapsed && <span className="flex-1 truncate font-serif text-[17px] font-semibold">Multi-agent patterns</span>}
        <button
          type="button"
          onClick={onToggle}
          className="rounded p-1 text-faint hover:text-text"
          aria-label={collapsed ? "Show the patterns" : "Collapse the patterns"}
        >
          {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
        </button>
      </div>
      <div className={cn("flex-1 overflow-y-auto py-2", collapsed ? "flex flex-col items-center gap-1" : "px-2")}>
        {error && !collapsed && <p className="px-2 py-1 text-xs text-red">Couldn&apos;t read the patterns: {error.message}</p>}
        {patterns.length === 0 && !error && !collapsed && (
          <p className="px-2 py-1 text-xs text-faint">This hub has no pattern pack. Set patterns.dir to a pack folder.</p>
        )}
        {patterns.map((p) => {
          const ran = latestRoomOf(rooms, p.pattern) !== null;
          const on = p.pattern === current;
          const item = (
            <button
              key={p.pattern}
              type="button"
              onClick={() => onPick(p.pattern)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md text-left text-[13.5px]",
                collapsed ? "justify-center p-1.5" : "px-2 py-1.5",
                on ? "bg-elevated text-text" : "text-muted-foreground hover:bg-surface",
              )}
            >
              <span className="relative grid size-6 shrink-0 place-items-center rounded-md border border-border2 bg-paper text-[9.5px] font-semibold text-text">
                {initialsOf(p.title)}
                {ran && <span className="absolute -right-1 -top-1 size-2 rounded-full border-2 border-bg bg-green" />}
              </span>
              {!collapsed && <span className="truncate">{p.title}</span>}
            </button>
          );
          return collapsed ? (
            <Tooltip key={p.pattern} content={p.title} side="right">
              {item}
            </Tooltip>
          ) : (
            item
          );
        })}
      </div>
      {!collapsed && (
        <div className="border-t border-border px-4 py-3 text-xs text-faint">
          <Link href="/" className="hover:text-text">Open Mycelium</Link>
        </div>
      )}
    </nav>
  );
}

// ── a pattern not run yet ────────────────────────────────────────────────────

function IdleView({ pattern, onRan }: { pattern: PatternRead | null; onRan: () => void }) {
  if (!pattern) {
    return (
      <>
        <aside className="border-r border-border" />
        <main className="grid place-items-center text-sm text-faint">Pick a pattern.</main>
      </>
    );
  }
  const roles = rolesOf(pattern);
  return (
    <>
      <Attendants pattern={pattern} roles={roles} me="" floor={null} said={new Map()} />
      <main className="flex min-h-0 min-w-0 flex-col">
        <RunHeader pattern={pattern} room={null} onRan={onRan} />
        <BeforeAfter pattern={pattern} standing={null} state="idle" />
        <FlowBand flow={pattern.flow_spec} episode={null} floor={null} />
        <div className="grid flex-1 place-items-center px-8 text-center" data-guide="chat">
          <div className="max-w-md">
            <p className="font-serif text-2xl">{pattern.scenario.task.title}</p>
            <p className="mt-2 text-sm text-muted-foreground">{pattern.summary}</p>
            <p className="mt-4 text-sm text-faint">Run it to watch the team work. Each agent is a model playing a role; nobody is scripted.</p>
          </div>
        </div>
      </main>
    </>
  );
}

// ── a pattern's run ──────────────────────────────────────────────────────────

function RunView({ pattern, room, onRan }: { pattern: PatternRead; room: Room; onRan: () => void }) {
  const { principal } = useCurrentUser();
  const me = principal.trim().toLowerCase();
  const live = { refreshInterval: LIVE_MS };
  const { memories } = useRoomMemories(room.name, live);
  const { floors } = useRoomMembers(room.name, live);
  const { episodes } = useRoomEpisodes(room.name, live);
  const revalidate = useRoomRevalidate(room.name);

  const task = memories.find((m) => m.key === room.pattern_task) ?? null;
  const thread = task?.episode ?? null;
  const standing = standingOf(memories.find((m) => m.key === STANDING_KEY));
  const { messages, refresh } = useThreadMessages(room.name, thread, 200, live);
  useRoomStream(room.name, () => {
    refresh();
    revalidate();
  });

  const run = useMemo(() => latestRun(episodes, thread), [episodes, thread]);
  const floor = floors.find((f) => f.episode === thread) ?? null;
  const yourTurn = Boolean(me && floor?.speakers.some((s) => s.toLowerCase() === me));
  const closed = run && run.outcome !== "open" ? run.outcome : null;
  const state = closed ?? (yourTurn ? "yours" : run ? "running" : "loaded");

  const said = useMemo(() => {
    const last = new Map<string, string>();
    for (const m of messages) if (m.sender_handle && !conductorLineOf(m)) last.set(m.sender_handle.toLowerCase(), m.created_at ?? "");
    return last;
  }, [messages]);

  return (
    <>
      <Attendants pattern={pattern} roles={rolesOf(pattern)} me={me} floor={floor} said={said} />
      <main className="flex min-h-0 min-w-0 flex-col">
        <RunHeader pattern={pattern} room={room} onRan={onRan} />
        <BeforeAfter pattern={pattern} standing={standing} state={state} />
        <FlowBand flow={run?.flow ?? pattern.flow_spec} episode={run} floor={floor} />
        <Feed messages={messages} me={me} floor={floor} closed={closed} />
        <Composer room={room.name} thread={thread} me={me} yourTurn={yourTurn} closed={Boolean(closed)} onSent={refresh} />
      </main>
    </>
  );
}

/** The latest run of a flow in a task's thread. */
function latestRun(episodes: EpisodeSummary[], thread: string | null): EpisodeSummary | null {
  if (!thread) return null;
  const runs = episodes.filter((e) => e.within === thread && e.flow);
  runs.sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
  return runs[0] ?? null;
}

// ── the attendants ───────────────────────────────────────────────────────────

function Attendants({
  pattern,
  roles,
  me,
  floor,
  said,
}: {
  pattern: PatternRead;
  roles: Map<string, string>;
  me: string;
  floor: RoomFloor | null;
  said: Map<string, string>;
}) {
  const speakers = new Set((floor?.speakers ?? []).map((s) => s.toLowerCase()));
  return (
    <aside className="flex min-h-0 flex-col border-r border-border">
      <div className="flex h-12 shrink-0 items-center border-b border-border px-4 text-[11px] font-medium uppercase tracking-wider text-faint">
        In the room
      </div>
      <div className="flex-1 overflow-y-auto p-2" data-guide="members">
        {pattern.scenario.members.map((m) => {
          const human = m.kind === "human";
          const handle = human ? me || m.handle : m.handle;
          const up = speakers.has(handle.toLowerCase());
          const role = roles.get(m.handle) ?? (human ? "you" : m.kind);
          const spoke = said.get(handle.toLowerCase());
          const status = up ? (human ? "your turn" : "has the floor") : spoke ? `spoke ${clock(spoke)}` : role;
          const card = (
            <div className="whitespace-normal">
              <p className="text-[13px] font-semibold">
                {human ? "you" : m.handle} <span className="font-normal text-faint">{role}</span>
              </p>
              {m.description && <p className="mt-1 text-[12.5px] text-muted-foreground">{m.description}</p>}
              {m.notes && <p className="mt-2 line-clamp-5 whitespace-pre-line text-[12px] text-faint">{m.notes}</p>}
            </div>
          );
          return (
            <Tooltip key={m.handle} content={card} side="right" align="start" className="max-w-72 p-3">
              <div className={cn("flex cursor-default items-center gap-2.5 rounded-md px-2 py-1.5", up && "bg-surface")}>
                <span className={cn("relative rounded-full", up && "ring-2 ring-offset-2 ring-offset-bg", up && (human ? "ring-yellow" : "ring-accent"))}>
                  <Monogram handle={handle} className="size-7" color={human ? "var(--muted-foreground)" : undefined} />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13.5px] font-medium leading-tight">{human ? "you" : m.handle}</span>
                  <span className={cn("block truncate text-[11.5px] leading-tight", up ? (human ? "text-yellow" : "text-accent") : "text-faint")}>
                    {status}
                  </span>
                </span>
              </div>
            </Tooltip>
          );
        })}
        {pattern.flow && (
          <Tooltip
            content="It has no model of its own: it follows the flow and decides whose turn it is."
            side="right"
            align="start"
            className="max-w-72 p-3 text-[12.5px] text-muted-foreground"
          >
            <div className="mt-1 flex cursor-default items-center gap-2.5 rounded-md px-2 py-1.5 opacity-70">
              <Monogram handle="conductor" className="size-7" color="var(--faint)" />
              <span className="min-w-0">
                <span className="block text-[13.5px] font-medium leading-tight">conductor</span>
                <span className="block text-[11.5px] leading-tight text-faint">runs the flow</span>
              </span>
            </div>
          </Tooltip>
        )}
      </div>
    </aside>
  );
}

// ── the header ───────────────────────────────────────────────────────────────

function RunHeader({ pattern, room, onRan }: { pattern: PatternRead; room: Room | null; onRan: () => void }) {
  const { principal } = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const guide = useRef<TourHandle | null>(null);
  const stops = pattern.scenario.guide ?? [];

  const openGuide = () => {
    guide.current?.destroy();
    guide.current = startGuide(stops, () => {
      guide.current = null;
      writeFlag(GUIDED_KEY(pattern.pattern), true);
    });
  };
  // The first visit to a pattern walks through it once.
  useEffect(() => {
    if (stops.length === 0 || readFlag(GUIDED_KEY(pattern.pattern))) return;
    const t = window.setTimeout(openGuide, 600);
    return () => window.clearTimeout(t);
    // Once per pattern; the guide reads the page as it is when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pattern.pattern]);
  useEffect(() => () => guide.current?.destroy(), []);

  const run = async () => {
    setBusy(true);
    setFailed(null);
    try {
      await loadPattern(pattern.pattern, { run: true, created_by: principal });
      onRan();
    } catch (e) {
      setFailed(e instanceof ApiError || e instanceof Error ? e.message : "Couldn't start it");
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-faint">{pattern.title}</div>
        <div className="truncate text-[14px] font-medium leading-tight">{pattern.scenario.task.title}</div>
      </div>
      {failed && <span className="max-w-64 truncate text-xs text-red" title={failed}>{failed}</span>}
      {room && (
        <Link href={`/room/${encodeURIComponent(room.name)}`} className="flex items-center gap-1 text-xs text-faint hover:text-text">
          Open the room <ExternalLink className="size-3" />
        </Link>
      )}
      {stops.length > 0 && (
        <button type="button" onClick={openGuide} className="grid size-7 place-items-center rounded-full border border-border2 text-muted-foreground hover:text-text" aria-label="Walk me through it">
          <CircleHelp className="size-4" />
        </button>
      )}
      <button
        type="button"
        onClick={run}
        disabled={busy}
        className={cn(
          "flex items-center gap-1.5 rounded border px-3 py-1 text-[12.5px] font-medium disabled:opacity-60",
          room ? "border-border2 text-text hover:bg-surface" : "border-accent bg-accent text-accent-fg",
        )}
      >
        {room ? <RotateCcw className="size-3.5" /> : <Play className="size-3.5" />}
        {busy ? "Starting…" : room ? "Run again" : "Run it"}
      </button>
    </header>
  );
}

// ── before and after ─────────────────────────────────────────────────────────

const NOW_TONE: Record<string, { label: string; tone: string; box: string }> = {
  idle: { label: "Not run yet", tone: "text-faint", box: "border-border" },
  loaded: { label: "Starting", tone: "text-accent", box: "border-accent/40" },
  running: { label: "So far", tone: "text-accent", box: "border-accent/40" },
  yours: { label: "Waiting on you", tone: "text-yellow", box: "border-yellow/50 bg-yellow/5" },
  resolved: { label: "Done", tone: "text-green", box: "border-green/50 bg-green/5" },
  converged: { label: "Agreed", tone: "text-green", box: "border-green/50 bg-green/5" },
  rejected: { label: "Ended without it", tone: "text-yellow", box: "border-yellow/50 bg-yellow/5" },
};

function BeforeAfter({ pattern, standing, state }: { pattern: PatternRead; standing: Standing | null; state: string }) {
  const before = pattern.scenario.before;
  if (!before && !pattern.scenario.after) return null;
  const done = state === "resolved" || state === "converged" || state === "rejected";
  const tone = NOW_TONE[state] ?? NOW_TONE.running;
  const headline = standing?.headline ?? (state === "idle" ? "Run it to see where they land" : "Waiting for the first step…");
  return (
    <div className="grid shrink-0 grid-cols-[1fr_24px_1fr] items-stretch border-b border-border px-5 py-3">
      <div className="rounded-md border border-border bg-surface px-3.5 py-2.5" data-guide="before">
        <div className="text-[11.5px] text-faint">Before</div>
        <div className="mt-0.5 font-serif text-[19px] leading-snug">{before?.headline ?? pattern.scenario.task.title}</div>
        {before?.detail && <div className="mt-0.5 text-[12.5px] text-muted-foreground">{before.detail}</div>}
      </div>
      <div className="grid place-items-center text-faint">→</div>
      <div className={cn("rounded-md border bg-surface px-3.5 py-2.5", tone.box)} data-guide="after">
        <div className="flex justify-between text-[11.5px]">
          <span className="text-faint">{done ? "After" : "Now"}</span>
          <span className={tone.tone}>{tone.label}</span>
        </div>
        <div className={cn("mt-0.5 font-serif text-[19px] leading-snug", !standing && "text-muted-foreground")}>{headline}</div>
        {standing?.detail && <div className="mt-0.5 text-[12.5px] text-muted-foreground">{standing.detail}</div>}
      </div>
    </div>
  );
}

// ── the flow ─────────────────────────────────────────────────────────────────

function FlowBand({ flow, episode, floor }: { flow: EpisodeFlow | null; episode: EpisodeSummary | null; floor: RoomFloor | null }) {
  if (!flow) return null;
  return (
    <div className="flex shrink-0 items-center gap-4 overflow-x-auto border-b border-border px-5 py-2" data-guide="flow">
      <span className="w-28 shrink-0 text-xs text-faint">{flow.name}</span>
      <FlowGraph
        flow={flow}
        trace={episode?.trace ?? []}
        currentStep={episode?.current_step ?? null}
        outcome={episode?.outcome ?? "open"}
        floor={floor}
        className="max-h-32"
      />
    </div>
  );
}

// ── what was said ────────────────────────────────────────────────────────────

/** A conductor post as one quiet line between the messages, or null to skip it. */
function handoff(line: ConductorLine, me: string): string | null {
  switch (line.event) {
    case "open":
      return null;
    case "turn": {
      const who = line.to.toLowerCase() === me ? "your" : `${line.to}'s`;
      return `${who} turn${line.rounds && line.round && line.round > 1 ? ` · round ${line.round}` : ""}`;
    }
    case "edge":
      if (line.stance === "accept") return `${line.who} accepted`;
      if (line.stance === "reject") return `${line.who} pushed back · back to ${line.next}`;
      return null;
    case "select":
      return line.select.pick ? `picked option ${line.select.pick}` : "no option cleared the bar";
    case "close":
      return isSuccess(line.outcome) ? "done" : `ended · ${line.outcome}`;
  }
}

function Feed({ messages, me, floor, closed }: { messages: RoomMessage[]; me: string; floor: RoomFloor | null; closed: string | null }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [messages.length]);
  const waitingOn = closed ? [] : (floor?.speakers ?? []).filter((s) => s.toLowerCase() !== me);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto" data-guide="chat">
      <div className="mx-auto max-w-[700px] px-7 py-5">
        {messages.length === 0 && <p className="py-10 text-center text-sm text-faint">Starting the run…</p>}
        {messages.map((m, i) => {
          const line = conductorLineOf(m);
          if (line) {
            const text = handoff(line, me);
            return text ? <Divider key={m.id ?? i} text={text} /> : null;
          }
          const content = typeof m.content === "string" ? m.content : "";
          const stance = /stance=accept/.test(content) ? "approved" : /stance=reject/.test(content) ? "blocked" : null;
          const sender = m.sender_handle ?? "someone";
          const mine = sender.toLowerCase() === me;
          return (
            <div key={m.id ?? i} className="mb-1 flex gap-3">
              <Monogram handle={sender} className="size-7 shrink-0" color={mine ? "var(--muted-foreground)" : undefined} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-[13px] text-faint">
                  <span className="font-semibold text-text">{mine ? "you" : sender}</span>
                  {clock(m.created_at)}
                  {stance && <span className="rounded bg-yellow/10 px-1.5 text-[11px] text-yellow">{stance}</span>}
                </div>
                <MessageBody content={content.replace(MARKER, "").trim()} />
              </div>
            </div>
          );
        })}
        {waitingOn.length > 0 && (
          <div className="mt-2 flex items-center gap-3 text-[13px] text-faint">
            <Monogram handle={waitingOn[0]} className="size-7" />
            {waitingOn.join(", ")} {waitingOn.length > 1 ? "are" : "is"} responding…
          </div>
        )}
        <div ref={end} />
      </div>
    </div>
  );
}

function Divider({ text }: { text: string }) {
  return (
    <div className="my-4 flex items-center gap-3 text-xs text-faint">
      <span className="h-px flex-1 bg-border" />
      <span className="font-medium text-muted-foreground">{text}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

// ── the composer ─────────────────────────────────────────────────────────────

function Composer({
  room,
  thread,
  me,
  yourTurn,
  closed,
  onSent,
}: {
  room: string;
  thread: string | null;
  me: string;
  yourTurn: boolean;
  closed: boolean;
  onSent: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const send = async (content: string) => {
    if (!thread || !me || !content.trim()) return;
    setBusy(true);
    setFailed(null);
    try {
      await sendRoomMessage(room, { sender_handle: me, content, episode: thread });
      setText("");
      onSent();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Couldn't send it");
    } finally {
      setBusy(false);
    }
  };

  if (!me) {
    return <div className="shrink-0 px-5 pb-4 pt-2 text-center text-xs text-faint">Say who you are in Mycelium to take part.</div>;
  }
  return (
    <div className="shrink-0 px-5 pb-4 pt-2" data-guide="turn">
      <div className={cn("mx-auto max-w-[700px] rounded-md border px-3 py-2.5", yourTurn ? "border-yellow/60 bg-yellow/5" : "border-border2")}>
        {yourTurn && <div className="mb-1 text-xs text-yellow">It&apos;s your turn. Nothing happens until you answer.</div>}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !yourTurn) {
              e.preventDefault();
              void send(text);
            }
          }}
          rows={yourTurn ? 2 : 1}
          disabled={busy || !thread}
          placeholder={yourTurn ? "Your reason (optional to approve, worth giving to block)" : closed ? "Ask a follow-up…" : "Say something in the room…"}
          className="w-full resize-none bg-transparent text-[14px] text-text outline-none placeholder:text-faint"
        />
        {yourTurn && (
          <div className="mt-2 flex items-center gap-2">
            <button type="button" disabled={busy} onClick={() => void send(withStance(text, "accept"))} className="rounded border border-green/50 px-3 py-1 text-[12.5px] font-medium text-green hover:bg-green/10 disabled:opacity-60">
              Approve
            </button>
            <button type="button" disabled={busy} onClick={() => void send(withStance(text, "reject"))} className="rounded border border-red/45 px-3 py-1 text-[12.5px] font-medium text-red hover:bg-red/10 disabled:opacity-60">
              Block
            </button>
          </div>
        )}
        {failed && <p className="mt-1 text-xs text-red">{failed}</p>}
      </div>
    </div>
  );
}
