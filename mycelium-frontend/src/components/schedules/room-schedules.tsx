// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The room's schedules: each agent's recurring check-in, kept and fired by the
 * hub. A row per schedule (who it wakes, when, its pre-check, what its last
 * run did, and how many runs woke the agent against how many stayed quiet),
 * with Pause/Resume, Run now, Renew, Edit and Delete. Opening a row shows its
 * runs, quiet ones folded together. The footer is the cost: every run that
 * woke an agent was a model turn.
 */

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Clock, Loader2, Plus } from "lucide-react";
import {
  createSchedule,
  deleteSchedule,
  runSchedule,
  updateSchedule,
  type Schedule,
  type ScheduleEdit,
  type ScheduleResult,
  type ScheduleRun,
} from "@/lib/api";
import { useRoomSchedules } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { Ago, NowProvider, useNow } from "@/lib/relative-time";
import { useCurrentUser } from "@/components/current-user";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const SCHEDULE_CHANGED = "schedule_changed";

const STATE_TONE: Record<Schedule["state"], string> = {
  active: "var(--accent)",
  paused: "var(--yellow)",
  expired: "var(--faint)",
};

const RESULT_TONE: Record<ScheduleResult, string> = {
  woke: "text-accent",
  quiet: "text-faint",
  held: "text-yellow",
  busy: "text-yellow",
  error: "text-red",
};

const RESULT_HINT: Record<ScheduleResult, string> = {
  woke: "the agent was woken (a model turn)",
  quiet: "the pre-check found nothing; no turn spent",
  held: "a wake was already waiting for the agent",
  busy: "the agent was mid-turn",
  error: "the pre-check failed",
};

export function when(s: Pick<Schedule, "every" | "cron">): string {
  return s.every ? `every ${s.every}` : `cron ${s.cron ?? ""}`;
}

/** "in 12m", "in 3h", "in 2d"; "due" once it has passed. */
export function until(at: string | null | undefined, now: number): string {
  const ms = at ? Date.parse(at) : NaN;
  if (!Number.isFinite(ms)) return "–";
  const min = Math.floor((ms - now) / 60_000);
  if (min < 1) return "due";
  if (min < 60) return `in ${min}m`;
  const h = Math.floor(min / 60);
  if (h < 48) return `in ${h}h`;
  return `in ${Math.floor(h / 24)}d`;
}

/** The run history with consecutive quiet runs folded into one line. */
export function foldQuiet(runs: ScheduleRun[]): ({ run: ScheduleRun } | { quiet: number; key: string })[] {
  const out: ({ run: ScheduleRun } | { quiet: number; key: string })[] = [];
  for (const run of runs) {
    const last = out[out.length - 1];
    if (run.result === "quiet") {
      if (last && "quiet" in last) last.quiet += 1;
      else out.push({ quiet: 1, key: run.at });
    } else {
      out.push({ run });
    }
  }
  return out;
}

export function RoomSchedules({ roomName }: { roomName: string }) {
  const { schedules, checks, loading, refresh } = useRoomSchedules(roomName);
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  // A run, a pause, an edit: the hub pushes that it moved.
  useRoomStream(roomName, (data) => {
    if ((data as { type?: string }).type === SCHEDULE_CHANGED) refresh();
  });

  const turns = schedules.reduce((n, s) => n + (s.wakes ?? 0), 0);
  const quiet = schedules.reduce((n, s) => n + (s.quiet ?? 0), 0);

  return (
    <NowProvider>
      <div className="flex h-full min-h-0 flex-col bg-bg">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
          <Clock className="size-3.5 text-faint" />
          <span className="text-label text-text">Schedules</span>
          <span className="text-micro text-faint">check-ins the hub fires for agents in this room</span>
          <Button size="xs" variant="outline" className="ml-auto" onClick={() => setEditing("new")}>
            <Plus className="size-3" /> New
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {schedules.length === 0 ? (
            loading ? null : (
              <EmptyState
                icon={Clock}
                size="sm"
                className="h-full"
                title="No schedules"
                description="A schedule wakes an agent on an interval, after a cheap check finds something worth a turn."
                action={
                  <Button size="xs" onClick={() => setEditing("new")}>
                    New schedule
                  </Button>
                }
              />
            )
          ) : (
            <ScheduleTable roomName={roomName} schedules={schedules} onEdit={setEditing} onChanged={refresh} />
          )}
        </div>
        {schedules.length > 0 && (
          <div className="shrink-0 border-t border-border px-3 py-1.5 text-micro text-faint">
            {turns} model {turns === 1 ? "turn" : "turns"} spent by schedules here · {quiet} quiet{" "}
            {quiet === 1 ? "run" : "runs"} that cost none
          </div>
        )}
      </div>
      <ScheduleDialog
        roomName={roomName}
        editing={editing}
        checks={checks}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          refresh();
        }}
      />
    </NowProvider>
  );
}

function ScheduleTable({
  roomName,
  schedules,
  onEdit,
  onChanged,
}: {
  roomName: string;
  schedules: Schedule[];
  onEdit: (s: Schedule) => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <table className="w-full text-label">
      <thead>
        <tr className="border-b border-border bg-surface text-left text-micro text-faint">
          <th className="w-5" />
          <th className="px-2.5 py-1.5 font-normal">Schedule</th>
          <th className="px-2.5 py-1.5 font-normal">Check</th>
          <th className="px-2.5 py-1.5 font-normal">Next</th>
          <th className="px-2.5 py-1.5 font-normal">Last run</th>
          <th className="whitespace-nowrap px-2.5 py-1.5 text-right font-normal" title="Runs that woke the agent / stayed quiet">
            Woke · quiet
          </th>
          <th className="px-2.5 py-1.5" />
        </tr>
      </thead>
      <tbody>
        {schedules.map((s) => (
          <Fragment key={s.name}>
            <ScheduleRow
              roomName={roomName}
              schedule={s}
              open={open === s.name}
              onToggle={() => setOpen(open === s.name ? null : s.name)}
              onEdit={() => onEdit(s)}
              onChanged={onChanged}
            />
            {open === s.name && (
              <tr className="border-b border-hairline bg-surface/40">
                <td />
                <td colSpan={6} className="px-2.5 pb-2.5 pt-1">
                  <ScheduleDetail schedule={s} />
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function ScheduleRow({
  roomName,
  schedule: s,
  open,
  onToggle,
  onEdit,
  onChanged,
}: {
  roomName: string;
  schedule: Schedule;
  open: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const now = useNow();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not ${label.toLowerCase()}`);
    } finally {
      setBusy(null);
    }
  };

  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <>
      <tr className={cn("border-b border-hairline align-top", open && "border-b-0")}>
        <td className="pl-2 pt-2">
          <button type="button" onClick={onToggle} aria-label={open ? "Hide runs" : "Show runs"} className="text-faint hover:text-text">
            <Chevron className="size-3.5" />
          </button>
        </td>
        <td className="px-2.5 py-1.5">
          <button type="button" onClick={onToggle} className="inline-flex items-center gap-1.5 whitespace-nowrap text-left">
            <span
              aria-hidden
              className="size-1.5 rounded-full"
              style={{ background: STATE_TONE[s.state] }}
              title={s.state}
            />
            <span className="font-mono text-text">{s.name}</span>
            <span className="font-mono text-micro text-muted-foreground">@{s.owner}</span>
          </button>
          <span className="block text-micro text-faint">
            {when(s)}
            {s.state !== "active" && ` · ${s.state}`}
            {s.task && ` · ${s.task}`}
          </span>
          {error && <span className="block text-micro text-red">{error}</span>}
        </td>
        <td className="px-2.5 py-1.5 font-mono text-micro text-muted-foreground">{s.check}</td>
        <td className="px-2.5 py-1.5 text-micro text-muted-foreground">
          {s.state === "active" ? until(s.next_run, now) : "–"}
          <span className="block text-faint" title={s.expires_at}>
            {s.state === "expired" || until(s.expires_at, now) === "due"
              ? "expired"
              : `expires ${until(s.expires_at, now)}`}
          </span>
        </td>
        <td className="px-2.5 py-1.5 text-micro">
          {s.last_run && s.last_result ? (
            <span title={RESULT_HINT[s.last_result]}>
              <span className={RESULT_TONE[s.last_result]}>{s.last_result}</span>{" "}
              <Ago at={s.last_run} className="text-faint" />
            </span>
          ) : (
            <span className="text-faint">never</span>
          )}
        </td>
        <td className="px-2.5 py-1.5 text-right font-mono text-micro">
          <span className="text-text">{s.wakes ?? 0}</span>
          <span className="text-faint"> · {s.quiet ?? 0}</span>
        </td>
        <td className="whitespace-nowrap px-2.5 py-1.5 text-right">
          {busy && <Loader2 className="mr-1 inline size-3 animate-spin text-faint" />}
          {s.state !== "expired" && (
            <Button
              size="xs"
              variant="ghost"
              disabled={!!busy}
              onClick={() => void act(s.paused ? "Resume" : "Pause", () => updateSchedule(roomName, s.name, { paused: !s.paused }))}
            >
              {s.paused ? "Resume" : "Pause"}
            </Button>
          )}
          <Button size="xs" variant="ghost" disabled={!!busy} onClick={() => void act("Run", () => runSchedule(roomName, s.name))}>
            Run now
          </Button>
          <Button size="xs" variant="ghost" disabled={!!busy} onClick={() => void act("Renew", () => updateSchedule(roomName, s.name, { renew: true }))}>
            Renew
          </Button>
          <Button size="xs" variant="ghost" disabled={!!busy} onClick={onEdit}>
            Edit
          </Button>
          <Button
            size="xs"
            variant="ghost"
            className="text-red"
            disabled={!!busy}
            onClick={() => {
              if (window.confirm(`Delete schedule ${s.name}?`)) void act("Delete", () => deleteSchedule(roomName, s.name));
            }}
          >
            Delete
          </Button>
        </td>
      </tr>
    </>
  );
}

function ScheduleDetail({ schedule: s }: { schedule: Schedule }) {
  const runs = foldQuiet(s.history ?? []);
  return (
    <div className="space-y-2">
      {s.prompt && <p className="whitespace-pre-wrap text-label text-muted-foreground">{s.prompt}</p>}
      {runs.length === 0 ? (
        <p className="text-micro text-faint">No runs yet.</p>
      ) : (
        <ol className="space-y-1">
          {runs.map((item) =>
            "quiet" in item ? (
              <li key={`q-${item.key}`} className="text-micro text-faint">
                … {item.quiet} quiet {item.quiet === 1 ? "run" : "runs"}
              </li>
            ) : (
              <li key={item.run.at} className="text-micro">
                <span className={RESULT_TONE[item.run.result]} title={RESULT_HINT[item.run.result]}>
                  {item.run.result}
                </span>{" "}
                <Ago at={item.run.at} className="text-faint" />
                {item.run.trigger === "manual" && <span className="text-faint"> · by hand</span>}
                {!!item.run.missed && <span className="text-faint"> · stood in for {item.run.missed} missed</span>}
                {item.run.detail && <span className="block text-red">{item.run.detail}</span>}
                {(item.run.found ?? []).map((line) => (
                  <span key={line} className="block pl-3 text-muted-foreground">
                    – {line}
                  </span>
                ))}
                {(item.run.found_total ?? 0) > (item.run.found?.length ?? 0) && (
                  <span className="block pl-3 text-faint">
                    and {(item.run.found_total ?? 0) - (item.run.found?.length ?? 0)} more
                  </span>
                )}
              </li>
            ),
          )}
        </ol>
      )}
    </div>
  );
}

function ScheduleDialog({
  roomName,
  editing,
  checks,
  onClose,
  onSaved,
}: {
  roomName: string;
  editing: Schedule | "new" | null;
  checks: Record<string, string>;
  onClose: () => void;
  onSaved: () => void;
}) {
  return (
    <Dialog open={editing !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        {editing !== null && (
          <ScheduleForm
            key={editing === "new" ? "new" : editing.name}
            roomName={roomName}
            schedule={editing === "new" ? null : editing}
            checks={checks}
            onClose={onClose}
            onSaved={onSaved}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ScheduleForm({
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
  const [name, setName] = useState(schedule?.name ?? "");
  const [owner, setOwner] = useState(schedule?.owner ?? "");
  const [timing, setTiming] = useState(schedule?.cron ? "cron" : "every");
  const [every, setEvery] = useState(schedule?.every ?? "30m");
  const [cron, setCron] = useState(schedule?.cron ?? "0 9 * * 1-5");
  const [check, setCheck] = useState(schedule?.check ?? "always");
  const [task, setTask] = useState(schedule?.task ?? "");
  const [prompt, setPrompt] = useState(schedule?.prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    const when: ScheduleEdit = timing === "cron" ? { cron: cron.trim() } : { every: every.trim() };
    try {
      if (schedule) {
        await updateSchedule(roomName, schedule.name, { ...when, check, prompt, task: task.trim() });
      } else {
        await createSchedule(roomName, {
          name: name.trim(),
          owner: owner.trim().replace(/^@/, ""),
          prompt,
          check,
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

  const checkNames = Object.keys(checks).filter((c) => !c.startsWith("search:"));
  const label = "flex flex-col gap-1 text-micro text-faint";
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <DialogHeader>
        <DialogTitle>{schedule ? `Edit ${schedule.name}` : "New schedule"}</DialogTitle>
        <DialogDescription>
          The hub wakes the agent on this schedule, after its check finds something. A run that finds nothing costs no
          turn and posts nothing to the room.
        </DialogDescription>
      </DialogHeader>
      {!schedule && (
        <div className="grid grid-cols-2 gap-3">
          <label className={label}>
            Name
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="board-check" required />
          </label>
          <label className={label}>
            Agent
            <Input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="@builder" required />
          </label>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>
          Fires
          <select
            value={timing}
            onChange={(e) => setTiming(e.target.value)}
            className="h-8 rounded-md border border-border bg-bg px-2 text-label text-text"
          >
            <option value="every">every…</option>
            <option value="cron">on a cron line (UTC)</option>
          </select>
        </label>
        <label className={label}>
          {timing === "cron" ? "Cron line" : "Interval"}
          {timing === "cron" ? (
            <Input value={cron} onChange={(e) => setCron(e.target.value)} className="font-mono" />
          ) : (
            <Input value={every} onChange={(e) => setEvery(e.target.value)} placeholder="30m, 2h, 1d" className="font-mono" />
          )}
        </label>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>
          Check before waking
          <Input value={check} onChange={(e) => setCheck(e.target.value)} list="schedule-checks" className="font-mono" />
          <datalist id="schedule-checks">
            {checkNames.map((c) => (
              <option key={c} value={c}>
                {checks[c]}
              </option>
            ))}
          </datalist>
          <span>{checks[check] ?? (check.startsWith("search:") ? checks["search:<query>"] : "")}</span>
        </label>
        <label className={label}>
          Task (optional)
          <Input value={task} onChange={(e) => setTask(e.target.value)} placeholder="work/checkout" className="font-mono" />
        </label>
      </div>
      <label className={label}>
        What the agent is told
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          className="rounded-md border border-border bg-bg px-2 py-1.5 text-label text-text"
          placeholder="Look at the board and chase anything stuck."
        />
      </label>
      {error && (
        <p role="alert" className="break-words text-label text-red">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving && <Loader2 className="size-3 animate-spin" />}
          {schedule ? "Save" : "Create"}
        </Button>
      </DialogFooter>
    </form>
  );
}
