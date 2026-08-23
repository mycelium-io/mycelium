// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { Bot, Cpu, Globe, UserRound } from "lucide-react";
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
  shiftDay,
  streaks,
  today,
  weekdayIndex,
  type ActivityEvent,
  type ActorKind,
  type DayKey,
} from "@/lib/board/activity";

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
 * The log: what the room did, by day, in the reader's own clock.
 *
 * The board's other views ask what needs you now. This one is memory — the
 * answer to "what did we work on last week", and the surface that makes filling
 * a day in worth doing.
 */
export function BoardDaily({ events, tz, onTz, now }: Props) {
  const end = today(tz, now);
  const days = useMemo(() => byDay(events, tz), [events, tz]);
  const grid = useMemo(() => daysEnding(end, GRID_DAYS), [end]);
  const run = useMemo(() => streaks(days, end), [days, end]);

  const [selected, setSelected] = useState<DayKey>(end);
  const [range, setRange] = useState<Range>("day");

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

  return (
    <div className="flex flex-col gap-4 px-5 py-4">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <GoalRing count={todayCount} />
        <div className="min-w-0">
          <p className="text-body text-text">
            {todayCount === 0
              ? "Nothing logged today yet"
              : `${todayCount} logged today${todayCount >= DAILY_GOAL ? ", day filled" : ""}`}
          </p>
          <p className="font-mono text-micro text-muted-foreground">
            {run.current > 0 ? `${run.current}-day streak` : "streak broken"} · longest {run.longest} ·{" "}
            {summary.events.length} in view
          </p>
        </div>

        <label className="ml-auto flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-micro text-muted-foreground">
          <Globe className="size-3 shrink-0 text-faint" />
          <select
            value={tz}
            onChange={e => onTz(e.target.value)}
            className="max-w-[190px] bg-transparent font-mono text-micro text-text outline-none"
          >
            {[...new Set([tz, ...COMMON_ZONES])].map(zone => (
              <option key={zone} value={zone} className="bg-paper text-text">
                {zone}
              </option>
            ))}
          </select>
        </label>
      </header>

      <HeatGrid days={grid} counts={days} selected={selected} onSelect={setSelected} today={end} />

      <div className="flex flex-wrap items-center gap-2">
        {RANGES.map(r => (
          <button
            key={r.id}
            onClick={() => setRange(r.id)}
            className={cn(
              "rounded-full border px-2.5 py-0.5 font-mono text-micro transition-colors",
              range === r.id
                ? "border-accent/40 bg-accent-soft text-accent"
                : "border-border text-muted-foreground hover:text-text",
            )}
          >
            {r.label}
          </button>
        ))}
        <span className="font-mono text-micro text-faint">
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
  const colour = actorKind === "human" ? "var(--muted-foreground)" : "var(--accent)";
  // A fortnight of this actor's own days, so a lane shows a rhythm and not
  // just a total.
  const spark = daysEnding(end, 14).map(
    key => (days.get(key) ?? []).filter(e => e.actor.toLowerCase() === actor.toLowerCase()).length,
  );
  const peak = Math.max(1, ...spark);

  return (
    <section className="rounded-lg border border-border bg-surface/30 px-3 py-2.5">
      <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <Icon className="size-3.5 shrink-0" strokeWidth={1.8} style={{ color: colour }} />
        <span className="font-mono text-label" style={{ color: colour }}>
          @{actor}
        </span>
        <span className="rounded bg-hairline px-1.5 font-mono text-micro text-faint">{actorKind}</span>
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
            <span className="shrink-0 font-mono text-micro text-muted-foreground">{event.verb}</span>
            <span className="min-w-0 flex-1 truncate text-label text-text">{event.title}</span>
          </li>
        ))}
        {events.length > 8 && (
          <li className="pl-16 font-mono text-micro text-faint">+{events.length - 8} more</li>
        )}
      </ul>
    </section>
  );
}
