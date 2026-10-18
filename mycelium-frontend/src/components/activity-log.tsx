// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, Cpu, Globe, UserRound } from "lucide-react";
import { Select } from "@/components/ui/select";
import { Panel } from "@/components/metrics-parts";
import { useClientSetting } from "@/lib/client-settings";
import { useRoomAgents, useRoomEpisodes, useRoomMemories, useRoomMessages } from "@/lib/room-data";
import { cn } from "@/lib/utils";
import {
  COMMON_ZONES,
  DAILY_GOAL,
  byDay,
  daysEnding,
  digest,
  formatDay,
  formatTime,
  heatLevel,
  localZone,
  projectActivity,
  shiftDay,
  streaks,
  today,
  weekdayIndex,
  type ActivityEvent,
  type ActorKind,
  type DayKey,
} from "@/lib/board/activity";

/** How much chat the log reads back through. */
const MESSAGE_HISTORY = 300;

/**
 * A room's activity on the Metrics page: the day grid, the streak and who did
 * what, for the room picked. It was the board's Daily view; the board is now
 * for what's going on, and this is a record of what went on.
 */
export function ActivityPanel({ rooms }: { rooms: string[] }) {
  const [picked, setPicked] = useState("");
  const room = rooms.includes(picked) ? picked : (rooms[0] ?? "");
  const { messages } = useRoomMessages(room, MESSAGE_HISTORY);
  const { memories } = useRoomMemories(room);
  const { episodes } = useRoomEpisodes(room);
  const { agents } = useRoomAgents(room);
  // A day boundary is only meaningful in some zone, and which one is the
  // reader's business, so it is their time zone setting, not the room's.
  const [savedZone, chooseTz] = useClientSetting("general.time-zone");
  const tz = savedZone || localZone();

  // The clock starts on the client: the server render can't know "today".
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 60_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const events = useMemo(
    () =>
      projectActivity({
        room,
        messages,
        memories,
        episodes,
        agentHandles: agents.map(a => a.handle),
      }),
    [room, messages, memories, episodes, agents],
  );

  return (
    <Panel
      title="Activity"
      meta={
        rooms.length > 0 && (
          <Select
            aria-label="Room"
            value={room}
            onChange={e => setPicked(e.target.value)}
            size="xs"
            className="max-w-[200px]"
            selectClassName="font-mono text-micro"
          >
            {rooms.map(name => (
              <option key={name} value={name} className="bg-paper text-text">
                {name}
              </option>
            ))}
          </Select>
        )
      }
    >
      {room && now ? (
        <ActivityLog events={events} tz={tz} onTz={chooseTz} now={now} />
      ) : (
        <p className="px-4 py-3 text-label text-muted-foreground">No rooms yet, so there is nothing to show.</p>
      )}
    </Panel>
  );
}

interface Props {
  events: ActivityEvent[];
  tz: string;
  onTz: (tz: string) => void;
  now: number;
}

/** Ten weeks reads as a season of work without needing a scrollbar. */
const GRID_WEEKS = 10;
const GRID_DAYS = GRID_WEEKS * 7;

type Range = "day" | "week" | "last-week" | "month";

const RANGES: { id: Range; label: string }[] = [
  { id: "day", label: "This day" },
  { id: "week", label: "This week" },
  { id: "last-week", label: "Last week" },
  { id: "month", label: "30 days" },
];

/**
 * The log: what the room did, by day, in the reader's own clock. The answer
 * to "what did we work on last week", and the surface that makes filling a
 * day in worth doing.
 */
export function ActivityLog({ events, tz, onTz, now }: Props) {
  const end = today(tz, now);
  const days = useMemo(() => byDay(events, tz), [events, tz]);
  const grid = useMemo(() => daysEnding(end, GRID_DAYS), [end]);
  const run = useMemo(() => streaks(days, end), [days, end]);

  // It opens on the newest day anything happened, over 30 days, so a quiet
  // today or a fresh room doesn't open on an empty panel. A day picked on the
  // grid wins from then on.
  const latest = useMemo(
    () => [...days.keys()].filter(key => key <= end && (days.get(key)?.length ?? 0) > 0).sort().pop(),
    [days, end],
  );
  const [picked, setSelected] = useState<DayKey | null>(null);
  const selected = picked ?? latest ?? end;
  const [range, setRange] = useState<Range>("month");

  const span = useMemo(() => {
    // A week runs Monday to the selected day's Sunday, so "this week" means the
    // week you are looking at rather than the last seven days.
    const monday = shiftDay(selected, -weekdayIndex(selected));
    if (range === "week") return { from: monday, to: shiftDay(monday, 6) };
    if (range === "last-week") return { from: shiftDay(monday, -7), to: shiftDay(monday, -1) };
    if (range === "month") return { from: shiftDay(selected, -29), to: selected };
    return { from: selected, to: selected };
  }, [range, selected]);

  const summary = useMemo(() => digest(days, span.from, span.to), [days, span]);
  const todayCount = days.get(end)?.length ?? 0;
  // The header is about today only while today is in view and has something in
  // it. Otherwise it says what the view shows: a ring at zero and "streak
  // broken" over a range full of work reads as broken.
  const aboutToday = todayCount > 0 && span.from <= end && end <= span.to;

  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {aboutToday && <GoalRing count={todayCount} />}
        <div className="min-w-0">
          {aboutToday ? (
            <>
              <p className="text-body text-text">
                {`${todayCount} logged today${todayCount >= DAILY_GOAL ? ", day filled" : ""}`}
              </p>
              <p className="text-micro tabular text-muted-foreground">
                {run.current > 0 ? `${run.current}-day streak` : "streak broken"} · longest {run.longest} ·{" "}
                {summary.events.length} in view
              </p>
            </>
          ) : (
            <>
              <p className="text-body text-text">{rangeHeading(summary.activeDays, span.from, span.to)}</p>
              {/* Nothing in view: the heading says so, and a line of zeros adds nothing. */}
              {summary.events.length > 0 && (
                <p className="text-micro tabular text-muted-foreground">
                  {summary.events.length} logged · longest streak {run.longest}{" "}
                  {run.longest === 1 ? "day" : "days"}
                  {todayCount === 0 ? " · nothing logged today yet" : ` · ${todayCount} logged today`}
                </p>
              )}
            </>
          )}
        </div>

        <label className="ml-auto flex items-center gap-1.5 text-micro text-muted-foreground">
          <Globe className="size-3 shrink-0 text-faint" />
          <Select
            aria-label="Time zone"
            value={tz}
            onChange={e => onTz(e.target.value)}
            size="xs"
            className="max-w-[190px]"
            selectClassName="font-mono text-micro"
          >
            {[...new Set([tz, ...COMMON_ZONES])].map(zone => (
              <option key={zone} value={zone} className="bg-paper text-text">
                {zone}
              </option>
            ))}
          </Select>
        </label>
      </header>

      <HeatGrid days={grid} counts={days} selected={selected} onSelect={setSelected} today={end} />

      <div className="flex flex-wrap items-center gap-2">
        {RANGES.map(r => (
          <button
            key={r.id}
            onClick={() => setRange(r.id)}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-micro transition-colors",
              range === r.id
                ? "border-accent/40 bg-accent-soft text-accent"
                : "border-border text-muted-foreground hover:text-text",
            )}
          >
            {r.label}
          </button>
        ))}
        <span className="text-micro tabular text-faint">
          {span.from === span.to
            ? formatDay(span.from)
            : `${formatDay(span.from, { weekday: undefined })} to ${formatDay(span.to, { weekday: undefined })}`}
          {" · "}
          {summary.activeDays} active {summary.activeDays === 1 ? "day" : "days"}
        </span>
      </div>

      {summary.events.length === 0 ? (
        <p className="py-8 text-center text-label text-muted-foreground">
          Nothing logged in this range. Pick another day, or widen it.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {summary.actors.map(lane => (
            <ActorLane
              key={lane.actor}
              actor={lane.actor}
              actorKind={lane.actorKind}
              events={lane.events}
              days={days}
              end={selected}
              tz={tz}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** What a view that isn't today shows, as one sentence:
 *  "2 active days from July 30 to August 28", or "Nothing logged on Monday, August 3". */
export function rangeHeading(activeDays: number, from: DayKey, to: DayKey): string {
  const when =
    from === to
      ? `on ${formatDay(from)}`
      : `from ${formatDay(from, { weekday: undefined })} to ${formatDay(to, { weekday: undefined })}`;
  if (activeDays === 0) return `Nothing logged ${when}`;
  return `${activeDays} active ${activeDays === 1 ? "day" : "days"} ${when}`;
}

/** How full today is. A ring rather than a number, because filling it is the point. */
function GoalRing({ count }: { count: number }) {
  const filled = Math.min(1, count / DAILY_GOAL);
  const full = filled >= 1;
  return (
    <div className="relative size-11 shrink-0">
      <svg viewBox="0 0 36 36" className="size-11 -rotate-90">
        <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--border)" strokeWidth="3" />
        <circle
          cx="18"
          cy="18"
          r="15.5"
          fill="none"
          stroke={full ? "var(--green)" : "var(--accent)"}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${filled * 97.4} 97.4`}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-micro tabular text-text">
        {count}
      </span>
    </div>
  );
}

const HEAT: Record<number, string> = {
  0: "var(--hairline)",
  1: "color-mix(in srgb, var(--accent) 22%, transparent)",
  2: "color-mix(in srgb, var(--accent) 45%, transparent)",
  3: "color-mix(in srgb, var(--accent) 70%, transparent)",
  4: "var(--accent)",
};

const WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"];

function HeatGrid({
  days,
  counts,
  selected,
  onSelect,
  today: end,
}: {
  days: DayKey[];
  counts: Map<DayKey, ActivityEvent[]>;
  selected: DayKey;
  onSelect: (key: DayKey) => void;
  today: DayKey;
}) {
  // Columns are weeks, rows are weekdays: the shape everyone already reads.
  const weeks: DayKey[][] = [];
  for (const key of days) {
    const index = weekdayIndex(key);
    if (index === 0 || weeks.length === 0) weeks.push([]);
    weeks[weeks.length - 1][index] = key;
  }

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1">
      <div className="flex shrink-0 flex-col gap-[3px] pr-1 pt-[1px]">
        {WEEKDAYS.map((label, i) => (
          <span key={i} className="flex h-3 items-center font-mono text-micro leading-none text-faint">
            {i % 2 === 1 ? label : ""}
          </span>
        ))}
      </div>
      {weeks.map((week, w) => (
        <div key={w} className="flex shrink-0 flex-col gap-[3px]">
          {Array.from({ length: 7 }, (_, d) => {
            const key = week[d];
            if (!key) return <span key={d} className="size-3" />;
            const count = counts.get(key)?.length ?? 0;
            const isToday = key === end;
            return (
              <button
                key={d}
                onClick={() => onSelect(key)}
                title={`${formatDay(key)} · ${count} logged`}
                className={cn(
                  "size-3 rounded-[3px] transition-transform hover:scale-125",
                  key === selected && "ring-2 ring-accent ring-offset-1 ring-offset-bg",
                  isToday && key !== selected && "ring-1 ring-border2",
                )}
                style={{ background: HEAT[heatLevel(count)] }}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

const ACTOR_ICON: Record<ActorKind, typeof Bot> = {
  agent: Bot,
  engine: Cpu,
  human: UserRound,
};

function ActorLane({
  actor,
  actorKind,
  events,
  days,
  end,
  tz,
}: {
  actor: string;
  actorKind: ActorKind;
  events: ActivityEvent[];
  days: Map<DayKey, ActivityEvent[]>;
  end: DayKey;
  tz: string;
}) {
  const Icon = ACTOR_ICON[actorKind];
  const color = actorKind === "human" ? "var(--muted-foreground)" : "var(--accent)";
  // A fortnight of this actor's own days, so a lane shows a rhythm and not
  // just a total.
  const spark = daysEnding(end, 14).map(
    key => (days.get(key) ?? []).filter(e => e.actor.toLowerCase() === actor.toLowerCase()).length,
  );
  const peak = Math.max(1, ...spark);

  return (
    <section className="rounded-lg border border-border bg-surface/30 px-3 py-2.5">
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Icon className="size-3.5 shrink-0" strokeWidth={1.8} style={{ color }} />
        <span className="text-label" style={{ color }}>
          @{actor}
        </span>
        <span className="rounded bg-hairline px-1.5 text-micro text-faint">{actorKind}</span>
        <span className="tabular text-micro text-muted-foreground">{events.length} logged</span>
        <span className="ml-auto flex items-end gap-[2px]" aria-hidden>
          {spark.map((count, i) => (
            <span
              key={i}
              className="w-[3px] rounded-[1px]"
              style={{
                height: `${3 + (count / peak) * 11}px`,
                background: count ? "var(--accent)" : "var(--border2)",
                opacity: count ? 0.35 + (count / peak) * 0.65 : 1,
              }}
            />
          ))}
        </span>
      </header>

      <ul className="mt-1.5 flex flex-col gap-1">
        {events.slice(0, 8).map(event => (
          <li key={event.id} className="flex items-baseline gap-2">
            <span className="w-14 shrink-0 whitespace-nowrap tabular text-micro text-faint">
              {formatTime(event.at, tz)}
            </span>
            <span className="shrink-0 text-micro text-muted-foreground">{event.action}</span>
            <span className="min-w-0 flex-1 truncate text-label text-text">{event.title}</span>
          </li>
        ))}
        {events.length > 8 && (
          <li className="pl-16 text-micro tabular text-faint">{events.length - 8} more</li>
        )}
      </ul>
    </section>
  );
}
