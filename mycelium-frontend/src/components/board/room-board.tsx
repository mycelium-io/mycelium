// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Kanban,
  ListChecks,
  Rows3,
  CalendarDays,
  Search,
  SlidersHorizontal,
  Table as TableIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCurrentUser } from "@/components/current-user";
import { useNotifications } from "@/components/notifications-provider";
import { ScrollArea } from "@/components/ui/scroll-area";
import { EmptyState } from "@/components/empty-state";
import {
  useRoom,
  useRoomEpisodes,
  useRoomMemories,
  useRoomMessages,
  useRoomRevalidate,
  useRoomRoster,
  useRoomStatus,
} from "@/lib/room-data";
import { createMemories, writeFields, writeLease } from "@/lib/api";
import { custodyRefusal } from "@/lib/board/custody";
import { planFieldWrite } from "@/lib/board/write-plan";
import { applyVerb, LENSES, type Lens, type LiveItem, type Verb } from "@/lib/board/item";
import { projectItems } from "@/lib/board/projection";
import { attachUpstream } from "@/lib/board/upstream";
import { localZone, projectActivity } from "@/lib/board/activity";
import { captureToMemory, type ParsedCapture } from "@/lib/board/capture";
import { groupableFields, inferSchema } from "@/lib/board/schema";
import { applyView, filterItems, lensCounts, SAVED_VIEWS, sortItems, UNGROUPED, type ViewConfig, type ViewMode } from "@/lib/board/view";
import { BoardCockpit, summarize } from "./board-cockpit";
import { BoardKanban } from "./board-kanban";
import { BoardTable } from "./board-table";
import { BoardTimeline } from "./board-timeline";
import { BoardCapture } from "./board-capture";
import { BoardDaily } from "./board-daily";
import { earcon, type Earcon } from "@/lib/board/earcons";

const MODES: { id: ViewMode; label: string; icon: typeof Rows3 }[] = [
  { id: "cockpit", label: "Cockpit", icon: Rows3 },
  { id: "board", label: "Board", icon: Kanban },
  { id: "table", label: "Table", icon: TableIcon },
  { id: "timeline", label: "Timeline", icon: ListChecks },
  { id: "daily", label: "Daily", icon: CalendarDays },
];

/** The board's clock ticks slowly: ages and TTL bars, not a stopwatch. */
const TICK_MS = 30_000;

/** How much chat the log reads back through. */
const MESSAGE_HISTORY = 300;

const TZ_KEY = "mycelium.board.tz";

interface Props {
  roomName: string;
}

/**
 * The room's coordination surface.
 *
 * Everything on it is a projection: rows come from the episodes, the
 * memory namespaces and presence; the schema comes from the frontmatter those
 * rows already carry; and the cockpit, kanban and table are three configs over
 * one pipeline rather than three screens.
 */
export function RoomBoard({ roomName }: Props) {
  const { room } = useRoom(roomName);
  const { episodes } = useRoomEpisodes(roomName);
  const { memories } = useRoomMemories(roomName);
  const { agents, presence } = useRoomRoster(roomName);
  const { messages } = useRoomMessages(roomName, MESSAGE_HISTORY);
  const { status: upstream } = useRoomStatus(roomName);
  const revalidate = useRoomRevalidate(roomName);
  const { principal } = useCurrentUser();
  const actor = principal.replace(/^@/, "") || "you";

  // A day boundary is only meaningful in some zone, and which one is the
  // reader's business — so it is remembered per browser, not per room.
  const [tz, setTz] = useState(localZone);

  // The clock starts on the client. Ages and TTLs are relative to *now*, which
  // the server render can't know without the two disagreeing on the markup.
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    // Both the clock and the saved zone are facts only the client has; reading
    // them after mount keeps the server's render and the browser's agreeing.
    const first = setTimeout(() => {
      tick();
      try {
        const saved = window.localStorage.getItem(TZ_KEY);
        if (saved) setTz(saved);
      } catch {
        // A browser refusing storage just keeps the host's zone.
      }
    }, 0);
    const id = setInterval(tick, TICK_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const [view, setView] = useState<ViewConfig>(SAVED_VIEWS[0].config);
  const [savedView, setSavedView] = useState(SAVED_VIEWS[0].slug);
  const [overlay, setOverlay] = useState<Record<string, Record<string, unknown>>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const chooseTz = useCallback((zone: string) => {
    setTz(zone);
    try {
      window.localStorage.setItem(TZ_KEY, zone);
    } catch {
      // A browser refusing storage still gets the zone for this session.
    }
  }, []);
  const [echo, setEcho] = useState<string | null>(null);
  const captureRef = useRef<HTMLInputElement>(null);

  // The board borrows the notification sound setting rather than inventing a
  // second one: someone who silenced Mycelium silenced all of it.
  const { settings } = useNotifications();
  const play = useCallback(
    (name: Earcon) => {
      if (settings.soundEnabled) earcon(name, settings.soundVolume);
    },
    [settings.soundEnabled, settings.soundVolume],
  );

  // The log reads the same room, flattened into who did what and when.
  const activity = useMemo(
    () =>
      projectActivity({
        room: roomName,
        messages,
        memories,
        episodes,
        agentHandles: agents.map(a => a.handle),
      }),
    [roomName, messages, memories, episodes, agents],
  );

  const items = useMemo(
    () =>
      // The hub says which rows mention which external references, so the
      // answer lands by row id: no view re-parses a task's text.
      attachUpstream(
        projectItems({
          room: roomName,
          episodes,
          memories,
          agents,
          presence,
          now: new Date(now).toISOString(),
          overlay,
        }),
        upstream,
      ),
    [roomName, episodes, memories, agents, presence, now, overlay, upstream],
  );

  // One pass over every row's frontmatter gives the columns, the kanban's
  // groupings and the table's editors — nothing about the schema is declared.
  const schema = useMemo(() => inferSchema(items), [items]);
  const groupable = useMemo(() => groupableFields(schema), [schema]);
  const counts = useMemo(() => lensCounts(items, now), [items, now]);

  // Watching the board is optional; hearing it is the point. Only a *growing*
  // steer-lens speaks, and only after the first render has something to compare.
  const lastNeedsYou = useRef<number | null>(null);
  useEffect(() => {
    const previous = lastNeedsYou.current;
    lastNeedsYou.current = counts.needs_you;
    if (previous !== null && counts.needs_you > previous) play("needs_you");
  }, [counts.needs_you, play]);

  const groups = useMemo(() => applyView(items, view, schema, now), [items, view, schema, now]);
  const flat = useMemo(() => sortItems(filterItems(items, view, now), view, now), [items, view, now]);
  const ordered = useMemo(
    () => (view.mode === "cockpit" || view.mode === "board" ? groups.flatMap(g => g.items) : flat),
    [view.mode, groups, flat],
  );

  // What the surface shows between the gesture and the room's answer. It is a
  // guess, so it is only ever put on screen once a write is actually in flight,
  // and it is taken back down the moment the room has spoken — either because
  // the fresh row arrived, or because the write failed and there is nothing to
  // show. An overlay that outlives its write is the board disagreeing with the
  // hub until somebody reloads.
  const applyOverlay = useCallback((id: string, fields: Record<string, unknown>) => {
    setOverlay(prev => ({ ...prev, [id]: { ...(prev[id] ?? {}), ...fields } }));
  }, []);

  const clearOverlay = useCallback((id: string) => {
    setOverlay(prev => {
      if (!(id in prev)) return prev;
      return Object.fromEntries(Object.entries(prev).filter(([key]) => key !== id));
    });
  }, []);

  /**
   * A verb's write, and the only thing that reports it.
   *
   * Callers do not echo their own success: every one of them used to, which
   * meant a refusal set here was overwritten a line later by a caller claiming
   * the write had happened. Whether the room was told is this function's
   * business, so what the surface says about it is too.
   */
  const patch = useCallback(
    (item: LiveItem, fields: Record<string, unknown>, verb = "write") => {
      const plan = planFieldWrite(item, fields);
      if (plan === null) return;
      if ("refused" in plan) {
        setEcho(`${verb} ${item.id} — ${plan.refused}`);
        return;
      }
      applyOverlay(item.id, fields);
      const said = Object.entries(plan.writable)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(" ");
      void writeFields(roomName, { key: plan.key, handle: actor, fields: plan.writable })
        .then(async () => {
          setEcho(`${verb} ${plan.key} → ${said}`);
          await revalidate();
        })
        .catch((e: unknown) => setEcho(`${verb} ${item.id} failed — ${String(e)}`))
        .finally(() => clearOverlay(item.id));
    },
    [actor, applyOverlay, clearOverlay, revalidate, roomName],
  );

  const runVerb = useCallback(
    (item: LiveItem, verb: Verb) => {
      const fields = applyVerb(item, verb, { actor, now: new Date().toISOString() });
      setSelectedId(item.id);
      play(verb);

      // Custody moves under its own rules — a live claim is not stealable, and
      // expiry is read off a clock — so it keeps its own endpoint. A row that
      // cannot hold a lease is not out of luck: `resolve` on it is a stage
      // change, which is a plain field write like any other.
      const custodial = verb === "claim" || verb === "release" || verb === "resolve";
      const refusal = custodial ? custodyRefusal(item) : null;
      if (!custodial || refusal) {
        if (refusal && verb !== "resolve") {
          setEcho(`${verb} ${item.id} — ${refusal}`);
          return;
        }
        patch(item, fields, verb);
        return;
      }

      applyOverlay(item.id, fields);
      void writeLease(roomName, verb, { key: item.id.replace(/^memory:/, ""), handle: actor })
        .then(async state => {
          setEcho(`${verb} ${state.key} → custody=${state.custody} owner=${state.owner ?? "—"}`);
          await revalidate();
        })
        .catch((e: unknown) => setEcho(`${verb} ${item.id} failed — ${String(e)}`))
        .finally(() => clearOverlay(item.id));
    },
    [actor, applyOverlay, clearOverlay, patch, play, revalidate, roomName],
  );

  const answer = useCallback(
    (item: LiveItem, choice: string) => {
      patch(item, { status: "resolved", decision: choice }, "answer");
      play("answer");
    },
    [patch, play],
  );

  const capture = useCallback(
    (parsed: ParsedCapture) => {
      // A captured line is a memory, written the same way every other write is.
      // Holding it in this component instead would put a row on the board that
      // the room had never been told about, and lose it on reload.
      const memory = captureToMemory(parsed, actor);
      setEcho(`capture → ${memory.key}`);
      play("capture");
      void createMemories(roomName, [memory])
        .then(() => {
          setSelectedId(`memory:${memory.key}`);
          revalidate();
        })
        .catch((e: unknown) => setEcho(`capture ${memory.key} failed — ${String(e)}`));
    },
    [actor, play, revalidate, roomName],
  );

  const pick = useCallback(
    (delta: number) => {
      if (ordered.length === 0) return;
      const index = ordered.findIndex(i => i.id === selectedId);
      const next = index === -1 ? 0 : Math.min(ordered.length - 1, Math.max(0, index + delta));
      setSelectedId(ordered[next].id);
    },
    [ordered, selectedId],
  );

  const setMode = useCallback((mode: ViewMode) => setView(v => ({ ...v, mode })), []);

  // Keyboard-first triage: the verbs are one keystroke from wherever the caret
  // sits, and typing anywhere with a text cursor never reaches them.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (target?.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;

      const selected = ordered.find(i => i.id === selectedId) ?? null;
      const key = e.key.toLowerCase();

      if (key === "j" || e.key === "ArrowDown") return pick(1), e.preventDefault();
      if (key === "k" || e.key === "ArrowUp") return pick(-1), e.preventDefault();
      // `n` for a new row: `/` already belongs to the app-wide search palette.
      if (key === "n") {
        e.preventDefault();
        captureRef.current?.focus();
        return;
      }
      if (key === "escape") return setSelectedId(null);
      if (key === "v") {
        const index = MODES.findIndex(m => m.id === view.mode);
        return setMode(MODES[(index + 1) % MODES.length].id);
      }
      if (["1", "2", "3", "4"].includes(key)) {
        const lens = (["needs_you", "in_flight", "resolved", "all"] as const)[Number(key) - 1];
        return setView(v => ({ ...v, lens, showResolved: lens !== "needs_you" }));
      }
      if (!selected) return;
      const verbs: Record<string, Verb> = {
        c: "claim",
        e: "release",
        r: "resolve",
        b: "block",
        p: "promote",
        x: "dismiss",
      };
      if (verbs[key]) {
        e.preventDefault();
        runVerb(selected, verbs[key]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ordered, selectedId, pick, runVerb, view.mode, setMode]);

  const applySaved = (slug: string) => {
    const saved = SAVED_VIEWS.find(s => s.slug === slug);
    if (!saved) return;
    setSavedView(slug);
    setView({ ...saved.config, query: view.query });
  };

  const title = room?.title ?? roomName;
  const groupBy = view.groupBy;

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-bg">
      <BoardHeader
        title={title}
        summary={summarize(items)}
        counts={counts}
        lens={view.lens}
        onLens={lens => setView(v => ({ ...v, lens, showResolved: lens !== "needs_you" }))}
        query={view.query}
        onQuery={query => setView(v => ({ ...v, query }))}
        mode={view.mode}
        onMode={setMode}
        savedView={savedView}
        onSavedView={applySaved}
        groupBy={groupBy}
        groupable={groupable.map(f => f.name)}
        onGroupBy={name => setView(v => ({ ...v, groupBy: name }))}
        schemaSize={schema.length}
        rowCount={items.length}
        optionsOpen={optionsOpen}
        onOptions={() => setOptionsOpen(o => !o)}
      />

      <BoardCapture ref={captureRef} actor={actor} onCapture={capture} />

      <div className="min-h-0 flex-1">
        {ordered.length === 0 && view.mode !== "daily" ? (
          <EmptyState
            className="h-full"
            icon={ListChecks}
            title={view.lens === "needs_you" ? "Nothing needs you" : "No rows in this view"}
            description={
              view.lens === "needs_you"
                ? "The board self-populates from episodes, memories and presence. Widen the lens to see what's in flight."
                : "Loosen the filters, or capture something to start one."
            }
          />
        ) : view.mode === "daily" ? (
          <ScrollArea className="h-full">
            <BoardDaily events={activity} tz={tz} onTz={chooseTz} now={now} />
          </ScrollArea>
        ) : view.mode === "board" && groupBy ? (
          <BoardKanban
            groups={groups}
            groupBy={groupBy}
            now={now}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onMove={(item, field, value) => {
              // The "no value" column is not a value: dropping a card there
              // means clear the field, not write the column's own key into it.
              const cleared = value === UNGROUPED;
              patch(item, { [field]: cleared ? undefined : value }, "move");
              play("move");
            }}
          />
        ) : (
          <ScrollArea className="h-full">
            {view.mode === "cockpit" ? (
              <BoardCockpit
                groups={groups}
                now={now}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onVerb={runVerb}
                onAnswer={answer}
              />
            ) : view.mode === "table" ? (
              <BoardTable
                items={flat}
                schema={schema}
                now={now}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onEdit={(item, field, value) => {
                  patch(item, { [field]: value }, "edit");
                }}
                sort={view.sort}
                onSort={field =>
                  setView(v => ({
                    ...v,
                    sort: { field, dir: v.sort.field === field && v.sort.dir === "asc" ? "desc" : "asc" },
                  }))
                }
              />
            ) : (
              <BoardTimeline items={flat} now={now} selectedId={selectedId} onSelect={setSelectedId} />
            )}
          </ScrollArea>
        )}
      </div>

      <BoardFooter echo={echo} rows={ordered.length} total={items.length} />
    </div>
  );
}

function BoardHeader(props: {
  title: string;
  summary: string;
  counts: Record<Lens | "all", number>;
  lens: Lens | "all";
  onLens: (lens: Lens | "all") => void;
  query: string;
  onQuery: (q: string) => void;
  mode: ViewMode;
  onMode: (m: ViewMode) => void;
  savedView: string;
  onSavedView: (slug: string) => void;
  groupBy: string | null;
  groupable: string[];
  onGroupBy: (name: string | null) => void;
  schemaSize: number;
  rowCount: number;
  optionsOpen: boolean;
  onOptions: () => void;
}) {
  // Grouping and the schema are what a board or a table is *for*; in the
  // cockpit they are furniture, so they fold away until asked for.
  const showOptions = props.optionsOpen || props.mode === "board" || props.mode === "table";
  const lenses: (Lens | "all")[] = [...LENSES.map(l => l.id), "all"];
  const label: Record<string, string> = {
    ...Object.fromEntries(LENSES.map(l => [l.id, l.label])),
    all: "All",
  };

  return (
    <header className={cn("shrink-0 border-b border-border px-5 pt-4", !showOptions && "pb-2.5")}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate font-serif text-display italic leading-tight text-text">{props.title}</h2>
          <p className="mt-0.5 font-mono text-micro text-muted-foreground">{props.summary}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex items-center gap-0.5 rounded-lg bg-surface p-0.5">
          {lenses.map(lens => (
            <button
              key={lens}
              onClick={() => props.onLens(lens)}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-label transition-colors",
                props.lens === lens ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text",
              )}
            >
              {label[lens]}
              <span
                className={cn(
                  "tabular text-micro",
                  lens === "needs_you" && props.counts.needs_you > 0 ? "text-accent" : "text-faint",
                )}
              >
                {props.counts[lens]}
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-0.5 rounded-lg bg-surface p-0.5">
          {MODES.map(mode => {
            const Icon = mode.icon;
            return (
              <button
                key={mode.id}
                onClick={() => props.onMode(mode.id)}
                title={mode.label}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2 py-1 text-label transition-colors",
                  props.mode === mode.id ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text",
                )}
              >
                <Icon className="size-3.5" strokeWidth={1.8} />
                <span className="hidden @[46rem]:inline">{mode.label}</span>
              </button>
            );
          })}
        </div>

        <div className="flex min-w-[140px] flex-1 items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-border px-2 py-1">
            <Search className="size-3 shrink-0 text-faint" />
            <input
              value={props.query}
              onChange={e => props.onQuery(e.target.value)}
              placeholder="Filter rows…"
              className="min-w-0 flex-1 bg-transparent text-label text-text outline-none placeholder:text-faint"
            />
          </div>

            <button
            onClick={props.onOptions}
            title="Saved views, grouping, and the inferred schema"
            className={cn(
              "shrink-0 rounded-md px-2 py-1 font-mono text-micro transition-colors",
              showOptions ? "text-accent" : "text-faint hover:text-muted-foreground",
            )}
          >
            <span className="hidden @[40rem]:inline">views &amp; fields</span>
            <SlidersHorizontal className="size-3.5 @[40rem]:hidden" strokeWidth={1.9} />
          </button>
        </div>
      </div>

      <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1.5", showOptions ? "mt-2 pb-2.5" : "hidden")}>
        <span className="font-mono text-micro text-faint">saved views</span>
        {SAVED_VIEWS.map(saved => (
          <button
            key={saved.slug}
            onClick={() => props.onSavedView(saved.slug)}
            title={saved.hint}
            className={cn(
              "rounded-full border px-2 py-0.5 font-mono text-micro transition-colors",
              props.savedView === saved.slug
                ? "border-accent/40 bg-accent-soft text-accent"
                : "border-border text-muted-foreground hover:text-text",
            )}
          >
            {saved.slug}
          </button>
        ))}

        <span className="ml-auto flex items-center gap-2">
          <span className="font-mono text-micro text-faint">group by</span>
          {props.groupable.map(name => (
            <button
              key={name}
              onClick={() => props.onGroupBy(props.groupBy === name ? null : name)}
              className={cn(
                "rounded px-1.5 py-0.5 font-mono text-micro transition-colors",
                props.groupBy === name ? "bg-accent-soft text-accent" : "text-muted-foreground hover:bg-surface",
              )}
            >
              {name}
            </button>
          ))}
          <span
            className="rounded bg-hairline px-1.5 py-0.5 font-mono text-micro text-faint"
            title="Inferred from the frontmatter every projected row carries. Nothing here is declared."
          >
            schema: {props.schemaSize} fields ← {props.rowCount} rows
          </span>
        </span>
      </div>
    </header>
  );
}

function BoardFooter({
  echo,
  rows,
  total,
}: {
  echo: string | null;
  rows: number;
  total: number;
}) {
  return (
    <footer className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-5 py-1.5">
      <span className="hidden flex-wrap items-center gap-x-2 gap-y-1 font-mono text-micro text-faint @[34rem]:flex">
        <Key k="j/k" /> move
        <Key k="c" /> claim
        <Key k="r" /> resolve
        <Key k="b" /> block
        <Key k="p" /> promote
        <Key k="x" /> dismiss
        <Key k="n" /> capture
      </span>
      <span className="ml-auto flex items-center gap-2 font-mono text-micro">
        {echo && <span className="truncate text-accent" title={echo}>{echo}</span>}
        <span className="text-faint">
          {rows}/{total} rows
        </span>
      </span>
    </footer>
  );
}

function Key({ k }: { k: string }) {
  return (
    <kbd className="rounded border border-border bg-surface px-1 py-px font-mono text-micro text-muted-foreground">
      {k}
    </kbd>
  );
}
