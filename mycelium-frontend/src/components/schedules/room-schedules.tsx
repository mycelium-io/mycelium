// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The room's schedules: each agent's recurring check-in, kept and fired by the
 * hub. One row per schedule, with its actions behind a ⋯ menu. Clicking a row
 * opens its details and its recent runs.
 */

import { useState } from "react";
import { Clock, Loader2, MoreHorizontal, Plus } from "lucide-react";
import {
  createSchedule,
  deleteSchedule,
  runSchedule,
  updateSchedule,
  type Schedule,
  type ScheduleEdit,
  type ScheduleResult,
} from "@/lib/api";
import { useRoomSchedules } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { Ago, NowProvider, useNow } from "@/lib/relative-time";
import { useCurrentUser } from "@/components/current-user";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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

const STATE_LABEL: Record<Schedule["state"], { word: string; tone: string }> = {
  active: { word: "Active", tone: "var(--accent)" },
  paused: { word: "Paused", tone: "var(--yellow)" },
  expired: { word: "Expired", tone: "var(--faint)" },
};

/** How each run result reads, and its color. */
export const RESULT_LABEL: Record<ScheduleResult, { word: string; className: string }> = {
  woke: { word: "Woke agent", className: "text-accent" },
  quiet: { word: "Nothing to do", className: "text-muted-foreground" },
  held: { word: "Already queued", className: "text-yellow" },
  busy: { word: "Agent busy", className: "text-yellow" },
  error: { word: "Check failed", className: "text-red" },
};

export function when(s: Pick<Schedule, "every" | "cron">): string {
  return s.every ? `Every ${s.every}` : `Cron ${s.cron ?? ""}`;
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

export function RoomSchedules({ roomName }: { roomName: string }) {
  const { schedules, checks, loading, refresh } = useRoomSchedules(roomName);
  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  // A run, a pause, an edit: the hub pushes that it moved.
  useRoomStream(roomName, (data) => {
    if ((data as { type?: string }).type === SCHEDULE_CHANGED) refresh();
  });
  const shown = schedules.find((s) => s.name === viewing) ?? null;

  return (
    <NowProvider>
      <div className="flex h-full min-h-0 flex-col bg-bg">
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
          <span className="text-label text-text">Schedules</span>
          {schedules.length > 0 && <span className="text-micro text-faint">{schedules.length}</span>}
          <Button size="xs" variant="outline" className="ml-auto" onClick={() => setEditing("new")}>
            <Plus className="size-3" /> New schedule
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          {schedules.length === 0 ? (
            loading ? null : (
              <EmptyState
                icon={Clock}
                size="sm"
                className="h-full"
                title="No schedules yet"
                description="A schedule wakes an agent on a timer, when a quick check finds something for it to do."
                action={
                  <Button size="xs" onClick={() => setEditing("new")}>
                    New schedule
                  </Button>
                }
              />
            )
          ) : (
            <ScheduleTable
              roomName={roomName}
              schedules={schedules}
              onOpen={(s) => setViewing(s.name)}
              onEdit={setEditing}
              onChanged={refresh}
            />
          )}
        </div>
      </div>
      <ScheduleDetailDialog schedule={shown} onClose={() => setViewing(null)} />
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

const TH = "px-3 py-1.5 text-left font-normal";
const TD = "px-3 py-2";

function ScheduleTable({
  roomName,
  schedules,
  onOpen,
  onEdit,
  onChanged,
}: {
  roomName: string;
  schedules: Schedule[];
  onOpen: (s: Schedule) => void;
  onEdit: (s: Schedule) => void;
  onChanged: () => void;
}) {
  return (
    <table className="w-full text-label">
      <thead className="sticky top-0 z-10">
        <tr className="border-b border-border bg-surface text-micro text-faint">
          <th className={TH}>Name</th>
          <th className={TH}>Agent</th>
          <th className={TH}>Schedule</th>
          <th className={TH}>Check</th>
          <th className={TH}>Status</th>
          <th className={TH}>Next run</th>
          <th className={TH}>Last run</th>
          <th className="w-10" />
        </tr>
      </thead>
      <tbody>
        {schedules.map((s) => (
          <ScheduleRow
            key={s.name}
            roomName={roomName}
            schedule={s}
            onOpen={() => onOpen(s)}
            onEdit={() => onEdit(s)}
            onChanged={onChanged}
          />
        ))}
      </tbody>
    </table>
  );
}

function ScheduleRow({
  roomName,
  schedule: s,
  onOpen,
  onEdit,
  onChanged,
}: {
  roomName: string;
  schedule: Schedule;
  onOpen: () => void;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const now = useNow();
  const state = STATE_LABEL[s.state];
  const last = s.last_result ? RESULT_LABEL[s.last_result] : null;
  return (
    <tr
      onClick={onOpen}
      className="cursor-pointer border-b border-hairline transition-colors hover:bg-hairline"
    >
      <td className={cn(TD, "font-mono text-text")}>{s.name}</td>
      <td className={cn(TD, "font-mono text-muted-foreground")}>@{s.owner}</td>
      <td className={cn(TD, "whitespace-nowrap text-muted-foreground")}>{when(s)}</td>
      <td className={cn(TD, "font-mono text-muted-foreground")}>{s.check}</td>
      <td className={TD}>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-text">
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: state.tone }} />
          {state.word}
        </span>
      </td>
      <td className={cn(TD, "whitespace-nowrap text-muted-foreground")}>
        {s.state === "active" ? until(s.next_run, now) : "–"}
      </td>
      <td className={cn(TD, "whitespace-nowrap")}>
        {s.last_run && last ? (
          <>
            <span className={last.className}>{last.word}</span>{" "}
            <Ago at={s.last_run} className="text-faint" />
          </>
        ) : (
          <span className="text-faint">Never</span>
        )}
      </td>
      <td className="px-1 py-1 text-right" onClick={(e) => e.stopPropagation()}>
        <RowMenu roomName={roomName} schedule={s} onEdit={onEdit} onChanged={onChanged} />
      </td>
    </tr>
  );
}

function RowMenu({
  roomName,
  schedule: s,
  onEdit,
  onChanged,
}: {
  roomName: string;
  schedule: Schedule;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const item =
    "flex w-full items-center rounded-md px-2 py-1.5 text-left text-label text-text transition-colors hover:bg-hairline disabled:opacity-50";
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setError(null);
      }}
    >
      <PopoverTrigger
        aria-label={`${s.name} options`}
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
      >
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <MoreHorizontal className="size-4" />}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-44 p-1">
        <button type="button" disabled={busy} className={item} onClick={() => void act(() => runSchedule(roomName, s.name))}>
          Run now
        </button>
        {s.state !== "expired" && (
          <button
            type="button"
            disabled={busy}
            className={item}
            onClick={() => void act(() => updateSchedule(roomName, s.name, { paused: !s.paused }))}
          >
            {s.paused ? "Resume" : "Pause"}
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          className={item}
          onClick={() => void act(() => updateSchedule(roomName, s.name, { renew: true }))}
        >
          Renew
        </button>
        <button
          type="button"
          disabled={busy}
          className={item}
          onClick={() => {
            setOpen(false);
            onEdit();
          }}
        >
          Edit
        </button>
        <div className="my-1 h-px bg-hairline" />
        <button
          type="button"
          disabled={busy}
          className={cn(item, "text-red")}
          onClick={() => {
            if (window.confirm(`Delete the schedule "${s.name}"?`)) void act(() => deleteSchedule(roomName, s.name));
          }}
        >
          Delete
        </button>
        {error && <p className="px-2 py-1 text-micro text-red">{error}</p>}
      </PopoverContent>
    </Popover>
  );
}

function ScheduleDetailDialog({ schedule: s, onClose }: { schedule: Schedule | null; onClose: () => void }) {
  const now = useNow();
  return (
    <Dialog open={s !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        {s && (
          <>
            <DialogHeader>
              <DialogTitle className="font-mono">{s.name}</DialogTitle>
              <DialogDescription>
                Wakes @{s.owner} · {when(s).toLowerCase()} · check: {s.check}
              </DialogDescription>
            </DialogHeader>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-label">
              <dt className="text-faint">Status</dt>
              <dd className="text-text">{STATE_LABEL[s.state].word}</dd>
              <dt className="text-faint">Next run</dt>
              <dd className="text-text">{s.state === "active" ? until(s.next_run, now) : "–"}</dd>
              <dt className="text-faint">Expires</dt>
              <dd className="text-text">
                {s.state === "expired" || until(s.expires_at, now) === "due" ? "Expired" : until(s.expires_at, now)}
              </dd>
              {s.task && (
                <>
                  <dt className="text-faint">Task</dt>
                  <dd className="font-mono text-text">{s.task}</dd>
                </>
              )}
              <dt className="text-faint">Runs</dt>
              <dd className="text-text">
                {s.runs ?? 0} total, {s.wakes ?? 0} woke the agent
              </dd>
              {s.prompt && (
                <>
                  <dt className="text-faint">Prompt</dt>
                  <dd className="whitespace-pre-wrap text-text">{s.prompt}</dd>
                </>
              )}
            </dl>
            <div className="max-h-72 overflow-auto rounded-md border border-border">
              {(s.history ?? []).length === 0 ? (
                <p className="px-3 py-2 text-label text-faint">No runs yet.</p>
              ) : (
                <table className="w-full text-label">
                  <thead className="sticky top-0">
                    <tr className="border-b border-border bg-surface text-micro text-faint">
                      <th className={TH}>When</th>
                      <th className={TH}>Result</th>
                      <th className={TH}>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(s.history ?? []).map((run) => {
                      const result = RESULT_LABEL[run.result];
                      const notes = [
                        ...(run.found ?? []),
                        ...((run.found_total ?? 0) > (run.found?.length ?? 0)
                          ? [`and ${(run.found_total ?? 0) - (run.found?.length ?? 0)} more`]
                          : []),
                        ...(run.detail ? [run.detail] : []),
                      ];
                      return (
                        <tr key={run.at} className="border-b border-hairline align-top last:border-b-0">
                          <td className={cn(TD, "whitespace-nowrap text-muted-foreground")}>
                            <Ago at={run.at} />
                          </td>
                          <td className={cn(TD, "whitespace-nowrap", result.className)}>
                            {result.word}
                            {run.trigger === "manual" && <span className="text-faint"> (manual)</span>}
                          </td>
                          <td className={cn(TD, "text-muted-foreground")}>
                            {notes.length === 0 && !run.missed ? (
                              <span className="text-faint">–</span>
                            ) : (
                              notes.map((line) => (
                                <span key={line} className="block">
                                  {line}
                                </span>
                              ))
                            )}
                            {!!run.missed && (
                              <span className="block text-faint">Caught up {run.missed} missed runs</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
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
          On each run the hub does a quick check first, and only wakes the agent if the check finds something.
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
