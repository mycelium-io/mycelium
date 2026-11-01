// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo } from "react";
import { CircleCheck, CircleX, FileText } from "lucide-react";
import { useThreadMessages } from "@/lib/room-data";
import {
  conductorLineOf,
  isSuccess,
  leastSatisfied,
  percent,
  standings,
  type ConductorLine,
  type LockRecord,
  type PickRecord,
} from "@/lib/conductor-line";
import { Button } from "@/components/ui/button";
import { OptionList, SatisfactionBars, type SatisfactionRow } from "@/components/task/satisfaction-bars";

type Close = Extract<ConductorLine, { event: "close" }>;

/** The last run in a thread that closed: how it ended, and its last pick or
 *  shared summary. `null` while a run is going, or when none ran here. */
export function closedRun(lines: ConductorLine[]): { close: Close; pick: PickRecord | null; lock: LockRecord | null } | null {
  let close: Close | null = null;
  let pick: PickRecord | null = null;
  let lock: LockRecord | null = null;
  for (const line of lines) {
    if (line.event === "open") {
      close = null;
      pick = null;
      lock = null;
    } else if (line.event === "select") pick = line.select;
    else if (line.event === "lock") lock = line.lock;
    else if (line.event === "close") close = line;
  }
  return close ? { close, pick, lock } : null;
}

/**
 * What a conductor run produced, at the top of its thread once it closes, so
 * the thread opens on the result rather than on the prompts that led to it.
 * Concord leads with the option picked and how satisfied each member is with
 * it; Accord with the shared summary and how much is still open in it. Each
 * opens what was saved.
 */
export function RunResult({
  roomName,
  episode,
  onOpenMemory,
}: {
  roomName: string;
  episode: string;
  onOpenMemory?: (key: string) => void;
}) {
  const { messages } = useThreadMessages(roomName, episode);
  const result = useMemo(() => {
    const run = closedRun(
      [...messages]
        .reverse()
        .map((m) => conductorLineOf(m))
        .filter((l): l is ConductorLine => l !== null),
    );
    return run ? describeResult(run) : null;
  }, [messages]);
  if (!result) return null;
  const Icon = result.good ? CircleCheck : CircleX;

  return (
    <section aria-label="Result" className="border-b border-border px-4 py-3">
      <div className="flex items-start gap-2">
        <Icon
          className="mt-0.5 size-4 flex-shrink-0"
          style={{ color: result.good ? "var(--green)" : "var(--yellow)" }}
          aria-label={result.good ? "succeeded" : "ended short"}
        />
        <h3 className="min-w-0 flex-1 text-label font-medium text-muted-foreground">
          {result.lead}
          {result.name && (
            <>
              {" "}
              <span className="text-text" title={result.title}>
                {result.name}
              </span>
            </>
          )}
          {result.count && <span className="font-normal"> {result.count}</span>}
        </h3>
        {result.memory && onOpenMemory && (
          <Button size="xs" variant="secondary" onClick={() => onOpenMemory(result.memory!)} title={result.memory}>
            <FileText className="size-3.5" />
            {result.kind === "decision" ? "Open decision" : "Open summary"}
          </Button>
        )}
      </div>
      {result.options && result.options.length > 0 && (
        <div className="ml-6 mt-2">
          <OptionList options={result.options} picked={result.name} />
        </div>
      )}
      {result.bars && (
        <div className="ml-6 mt-3">
          <SatisfactionBars
            label="How satisfied each member is with the pick"
            bar={result.bars.bar}
            rows={result.bars.rows}
            showBar
          />
          {result.least && (
            <p className="mt-1.5 text-micro text-muted-foreground">
              <span className="font-medium text-text">{result.least.member}</span> is least satisfied, at{" "}
              {percent(result.least.placed)} of the way to their ideal
            </p>
          )}
        </div>
      )}
    </section>
  );
}

interface Result {
  good: boolean;
  kind: "decision" | "summary";
  /** "Picked", "Best found:", "Shared summary". */
  lead: string;
  /** What was picked, by its letter, and its whole text. */
  name?: string;
  title?: string;
  /** Every option weighed, by letter, listed once. */
  options?: { letter: string; text: string }[];
  /** "17 points, 4 open". */
  count?: string;
  memory: string | null;
  bars: { bar?: number; rows: SatisfactionRow[] } | null;
  least: { member: string; placed: number } | null;
}

/** A closed run as the result strip says it, from its last pick or shared summary. */
export function describeResult(run: NonNullable<ReturnType<typeof closedRun>>): Result {
  const { close, pick, lock } = run;
  const memory = close.memory ?? (lock?.saved ? lock.memory : null);
  const good = isSuccess(close.outcome);
  if (pick?.pick) {
    return {
      good,
      kind: "decision",
      lead: close.outcome === "converged" ? "Picked" : close.outcome === "resolved" ? "Best found:" : "No agreement. Best was",
      name: pick.pick,
      title: pick.text,
      options: pick.options.map((o) => ({ letter: o.label, text: o.text })),
      memory,
      bars: {
        bar: pick.threshold / 100,
        rows: standings(pick, pick.pick).map((s) => ({ key: s.member, label: s.member, placed: s.placed, why: s.why })),
      },
      least: leastSatisfied(pick),
    };
  }
  if (lock) {
    return {
      good,
      kind: "summary",
      lead: "Shared summary",
      count: `${lock.points} ${lock.points === 1 ? "point" : "points"}${lock.flagged > 0 ? `, ${lock.flagged} open` : ""}`,
      memory,
      bars: null,
      least: null,
    };
  }
  return { good, kind: "summary", lead: `${close.protocol} ${good ? "done" : close.outcome}`, memory, bars: null, least: null };
}
