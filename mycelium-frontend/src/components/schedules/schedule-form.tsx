// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Making or changing a schedule, read top to bottom as the sentence it is:
 * wake this agent, this often, only when this is true, and tell it this. The
 * agent and the task are picked from the room rather than typed; the timing is
 * a few common choices with a custom line behind them; each pre-check says in
 * words what it looks for. A summary at the foot says what will happen.
 */

import { useMemo, useState } from "react";
import { Check, ChevronRight, Loader2 } from "lucide-react";
import { createSchedule, updateSchedule, type Schedule, type ScheduleEdit } from "@/lib/api";
import { memoryTitle } from "@/lib/memory-preview";
import { useRoomAgents, useRoomMemories } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Monogram } from "@/components/ui/monogram";
import { DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/** The timings offered as one click; anything else is Custom. */
export const PRESETS = ["15m", "30m", "1h", "4h"] as const;

export type Timing =
  | { kind: "every"; every: string }
  | { kind: "daily"; time: string; weekdays: boolean }
  | { kind: "custom"; text: string };

/** The cron line a daily timing fires on: minute, hour, every day or Monday to Friday. */
export function dailyCron(time: string, weekdays: boolean): string {
  const [h, m] = time.split(":").map((n) => Number.parseInt(n, 10));
  return `${Number.isFinite(m) ? m : 0} ${Number.isFinite(h) ? h : 9} * * ${weekdays ? "1-5" : "*"}`;
}

/** What a timing sends the hub: an interval, or a cron line (a custom one has spaces). */
export function timingEdit(t: Timing): ScheduleEdit {
  if (t.kind === "every") return { every: t.every };
  if (t.kind === "daily") return { cron: dailyCron(t.time, t.weekdays) };
  const text = t.text.trim();
  return text.includes(" ") ? { cron: text } : { every: text };
}

/** The timing a saved schedule reads back as, so editing one opens where it is. */
export function timingOf(s: Pick<Schedule, "every" | "cron"> | null): Timing {
  if (!s) return { kind: "every", every: "30m" };
  if (s.every) {
    return (PRESETS as readonly string[]).includes(s.every)
      ? { kind: "every", every: s.every }
      : { kind: "custom", text: s.every };
  }
  const daily = /^(\d{1,2}) (\d{1,2}) \* \* (\*|1-5)$/.exec((s.cron ?? "").trim());
  if (daily) {
    const time = `${daily[2].padStart(2, "0")}:${daily[1].padStart(2, "0")}`;
    return { kind: "daily", time, weekdays: daily[3] === "1-5" };
  }
  return { kind: "custom", text: s.cron ?? "" };
}

/** A timing as the summary says it: "every 30m", "every weekday at 09:00 UTC". */
export function timingWords(t: Timing): string {
  if (t.kind === "every") return `every ${t.every}`;
  if (t.kind === "daily") return `every ${t.weekdays ? "weekday" : "day"} at ${t.time} UTC`;
  const text = t.text.trim();
  if (!text) return "on a timing you haven't set";
  return text.includes(" ") ? `on the cron line ${text} (UTC)` : `every ${text}`;
}

/** Each pre-check in words: its chip, what it looks for, and how the summary ends with it.
 *  A check the hub adds later shows under its own name with the hub's description. */
const CHECK_WORDS: Record<string, { title: string; means: string; when: string }> = {
  always: {
    title: "Always",
    means: "Wakes it on every run, without checking first.",
    when: "every time",
  },
  mentions: {
    title: "It was mentioned",
    means: "Someone @-mentioned it since the last run.",
    when: "if someone mentioned it since the last run",
  },
  assigned: {
    title: "Work is waiting",
    means: "A task was filed for it and nobody has picked it up.",
    when: "if a task for it is waiting to be picked up",
  },
  stale: {
    title: "Its work went stale",
    means: "A task it's holding hasn't been touched and is about to lapse.",
    when: "if a task it holds has gone stale",
  },
  silent: {
    title: "A teammate went quiet",
    means: "Someone else's claim on a task lapsed while they were away.",
    when: "if a teammate's claim lapsed",
  },
  task: {
    title: "A task moved",
    means: "The task you pick below had new messages.",
    when: "if its task had new messages",
  },
  search: {
    title: "A search matches",
    means: "New messages match the search you type below.",
    when: "if new messages match a search",
  },
};

const SEARCH = "search:<query>";

/** A check's key in the picker: every ``search:…`` is the one search option. */
export function checkKey(check: string): string {
  return check.startsWith("search:") ? "search" : check;
}

/** A schedule name from its agent and check, when the person gives none. */
export function defaultName(owner: string, check: string): string {
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return [slug(owner), slug(checkKey(check))].filter(Boolean).join("-") || "schedule";
}

export function ScheduleForm({
  roomName,
  schedule,
  checks,
  onClose,
  onSaved,
}: {
  roomName: string;
  schedule: Schedule | null;
  checks: Record<string, string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { principal } = useCurrentUser();
  const { agents } = useRoomAgents(roomName);
  const { memories } = useRoomMemories(roomName);
  const members = useMemo(() => agents.filter((a) => a.adapter !== "engine"), [agents]);
  const tasks = useMemo(
    () => memories.filter((m) => m.key.startsWith("work/")).map((m) => ({ key: m.key, title: memoryTitle(m) })),
    [memories],
  );

  const [owner, setOwner] = useState(schedule?.owner ?? "");
  const [timing, setTiming] = useState<Timing>(() => timingOf(schedule));
  const [check, setCheck] = useState(schedule?.check ?? "always");
  const [query, setQuery] = useState(
    schedule?.check.startsWith("search:") ? schedule.check.slice("search:".length) : "",
  );
  const [task, setTask] = useState(schedule?.task ?? "");
  const [prompt, setPrompt] = useState(schedule?.prompt ?? "");
  const [name, setName] = useState(schedule?.name ?? "");
  const [more, setMore] = useState(Boolean(schedule?.task));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handle = owner.trim().replace(/^@/, "");
  // An agent with no manifest here (typed by hand on a CLI-made schedule) still shows.
  const picked = handle && !members.some((m) => m.handle === handle) ? [{ handle }] : [];
  const sentCheck = checkKey(check) === "search" ? `search:${query.trim()}` : check;
  const needsTask = checkKey(check) === "task";
  const options = Object.keys(checks).map((c) => (c === SEARCH ? "search" : c));
  const missing = !handle
    ? "Pick an agent to wake."
    : timing.kind === "custom" && !timing.text.trim()
      ? "Say how often it runs."
      : checkKey(check) === "search" && !query.trim()
        ? "Say what to search for."
        : needsTask && !task
          ? "Pick the task it watches."
          : null;

  const save = async () => {
    if (missing) {
      setError(missing);
      return;
    }
    setSaving(true);
    setError(null);
    const when = timingEdit(timing);
    try {
      if (schedule) {
        await updateSchedule(roomName, schedule.name, { ...when, check: sentCheck, prompt, task: task.trim() });
      } else {
        await createSchedule(roomName, {
          name: name.trim() || defaultName(handle, sentCheck),
          owner: handle,
          prompt,
          check: sentCheck,
          task: task.trim() || undefined,
          created_by: principal.trim() || undefined,
          ...when,
        });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the schedule");
    } finally {
      setSaving(false);
    }
  };

  const ending = CHECK_WORDS[checkKey(check)]?.when ?? `when the ${check} check finds something`;
  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <DialogHeader>
        <DialogTitle>{schedule ? `Edit ${schedule.name}` : "New schedule"}</DialogTitle>
        <DialogDescription>
          Wake an agent on a timer. Each run checks first, so it only costs a turn when there&apos;s something to do.
        </DialogDescription>
      </DialogHeader>

      <Step n={1} label="Wake">
        {schedule ? (
          <AgentPill handle={handle} selected />
        ) : members.length + picked.length === 0 ? (
          <Input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="No agents in this room yet. Type a handle"
            aria-label="Agent"
          />
        ) : (
          <div role="radiogroup" aria-label="Agent" className="flex flex-wrap gap-2">
            {[...picked, ...members].map((a) => (
              <AgentPill
                key={a.handle}
                handle={a.handle}
                selected={a.handle === handle}
                onClick={() => setOwner(a.handle)}
              />
            ))}
          </div>
        )}
      </Step>

      <Step n={2} label="How often">
        <div role="radiogroup" aria-label="How often" className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <Segment
              key={p}
              selected={timing.kind === "every" && timing.every === p}
              onClick={() => setTiming({ kind: "every", every: p })}
            >
              {p}
            </Segment>
          ))}
          <Segment
            selected={timing.kind === "daily"}
            onClick={() => setTiming({ kind: "daily", time: "09:00", weekdays: true })}
          >
            Daily
          </Segment>
          <Segment
            selected={timing.kind === "custom"}
            onClick={() => setTiming({ kind: "custom", text: timing.kind === "every" ? timing.every : "" })}
          >
            Custom
          </Segment>
        </div>
        {timing.kind === "daily" && (
          <div className="mt-2 flex items-center gap-3 text-label text-muted-foreground">
            <span>at</span>
            <Input
              type="time"
              value={timing.time}
              onChange={(e) => setTiming({ ...timing, time: e.target.value })}
              className="w-28 font-mono"
              aria-label="Time (UTC)"
            />
            <span className="text-faint">UTC</span>
            <label className="ml-2 flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={timing.weekdays}
                onChange={(e) => setTiming({ ...timing, weekdays: e.target.checked })}
              />
              weekdays only
            </label>
          </div>
        )}
        {timing.kind === "custom" && (
          <div className="mt-2 flex flex-col gap-1">
            <Input
              value={timing.text}
              onChange={(e) => setTiming({ kind: "custom", text: e.target.value })}
              placeholder="e.g. 45m, 2h, 1d, or a cron line like 0 9 * * 1-5"
              className="font-mono"
              aria-label="Custom timing"
              autoFocus
            />
            <span className="text-micro text-faint">An interval, or a five-field cron line in UTC.</span>
          </div>
        )}
      </Step>

      <Step n={3} label="Only when">
        <div role="radiogroup" aria-label="Only when" className="flex flex-wrap gap-1.5">
          {options.map((c) => (
            <Segment
              key={c}
              plain
              selected={checkKey(check) === c}
              onClick={() => setCheck(c === "search" ? `search:${query}` : c)}
              title={checks[c === "search" ? SEARCH : c]}
            >
              {CHECK_WORDS[c]?.title ?? c}
            </Segment>
          ))}
        </div>
        <p className="text-micro text-faint">
          {CHECK_WORDS[checkKey(check)]?.means ?? checks[check] ?? ""}
        </p>
        {checkKey(check) === "search" && (
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setCheck(`search:${e.target.value}`);
            }}
            placeholder='e.g. "refund" from:operator'
            className="mt-2 font-mono"
            aria-label="Search"
            autoFocus
          />
        )}
        {needsTask && <TaskPicker tasks={tasks} task={task} onChange={setTask} className="mt-2" />}
      </Step>

      <Step n={4} label="And tell it">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          className="w-full rounded-md border border-border bg-bg px-3 py-2 text-label text-text placeholder:text-faint focus:border-accent/60 focus:outline-none"
          placeholder="e.g. Look at the board and chase anything stuck."
          aria-label="What the agent is told"
        />
      </Step>

      {!needsTask && (
        <div className="-mt-2">
          <button
            type="button"
            onClick={() => setMore(!more)}
            className="flex items-center gap-1 text-micro text-faint hover:text-muted-foreground"
            aria-expanded={more}
          >
            <ChevronRight className={cn("size-3 transition-transform", more && "rotate-90")} />
            More options
          </button>
          {more && (
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {!schedule && (
                <label className="flex flex-col gap-1 text-micro text-faint">
                  Name
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={defaultName(handle, sentCheck)}
                    className="font-mono"
                  />
                </label>
              )}
              <label className="flex flex-col gap-1 text-micro text-faint">
                About a task
                <TaskPicker tasks={tasks} task={task} onChange={setTask} optional />
              </label>
            </div>
          )}
        </div>
      )}

      <div className="rounded-md border border-border bg-surface/60 px-3 py-2 text-label text-muted-foreground">
        {handle ? (
          <>
            Wakes <span className="font-mono text-text">@{handle}</span> {timingWords(timing)}, {ending}
            {prompt.trim() ? (
              <>
                , and tells it: <span className="text-text">&ldquo;{firstWords(prompt)}&rdquo;</span>
              </>
            ) : (
              "."
            )}
          </>
        ) : (
          "Pick an agent to wake."
        )}
      </div>

      {error && (
        <p role="alert" className="-mt-2 break-words text-label text-red">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving && <Loader2 className="size-3 animate-spin" />}
          {schedule ? "Save" : "Create schedule"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function firstWords(text: string, max = 80): string {
  const line = text.trim().split("\n")[0];
  return line.length > max ? `${line.slice(0, max).trimEnd()}…` : line;
}

function Step({ n, label, children }: { n: number; label: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-micro font-medium uppercase tracking-wide text-faint">
        <span className="flex size-4 items-center justify-center rounded-full border border-border text-[10px]">
          {n}
        </span>
        {label}
      </h3>
      {children}
    </section>
  );
}

function Segment({
  selected,
  onClick,
  plain,
  title,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  /** Words rather than a value, so not set in mono. */
  plain?: boolean;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      title={title}
      className={cn(
        "rounded-md border px-3 py-1.5 text-label transition-colors",
        !plain && "font-mono",
        selected
          ? "border-accent/60 bg-accent-soft text-text"
          : "border-border bg-bg text-muted-foreground hover:bg-surface hover:text-text",
      )}
    >
      {children}
    </button>
  );
}

function AgentPill({ handle, selected, onClick }: { handle: string; selected: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      disabled={!onClick}
      className={cn(
        "flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 transition-colors",
        selected
          ? "border-accent/60 bg-accent-soft text-text"
          : "border-border bg-bg text-muted-foreground hover:bg-surface hover:text-text",
        !onClick && "cursor-default",
      )}
    >
      <Monogram handle={handle} className="size-6 text-[10px]" />
      <span className="font-mono text-label">@{handle}</span>
      {selected && onClick && <Check className="size-3 text-accent" />}
    </button>
  );
}

function TaskPicker({
  tasks,
  task,
  onChange,
  optional,
  className,
}: {
  tasks: { key: string; title: string }[];
  task: string;
  onChange: (key: string) => void;
  optional?: boolean;
  className?: string;
}) {
  // A schedule made on the CLI may name a task this room's list doesn't hold.
  const known = !task || tasks.some((t) => t.key === task);
  return (
    <select
      value={task}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Task"
      className={cn("h-8 w-full rounded-md border border-border bg-bg px-2 text-label text-text", className)}
    >
      <option value="">{optional ? "None" : "Pick a task…"}</option>
      {!known && <option value={task}>{task}</option>}
      {tasks.map((t) => (
        <option key={t.key} value={t.key}>
          {t.title}
        </option>
      ))}
    </select>
  );
}
