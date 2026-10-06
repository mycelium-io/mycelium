// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The flow an episode runs, drawn at the top of its thread: the graph, where
 * the run stands, whose turn it is, and the steps taken so far.
 *
 * The record is the source: the conductor writes the flow and its trace onto
 * the episode as it walks, so this reads the same thing a person would find
 * in `log/episodes/{id}.md`, and the floor it draws is the live one off the
 * roster. Shown only for an episode that carries a flow.
 */

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { EpisodeSummary, FlowTraceEntry, RoomFloor } from "@/lib/api";
import { lockSummary, tallySummary } from "@/lib/conductor-line";
import { FlowGraph } from "@/components/flow-graph";

// The graph is tall, and a thread is opened to read the conversation, so the
// flow starts as its one-line summary. Opening it is remembered per browser.
const SHOWN_KEY = "mycelium.flow-panel.shown";

function readShown(): boolean {
  try {
    return window.localStorage.getItem(SHOWN_KEY) === "1";
  } catch {
    return false;
  }
}

function writeShown(shown: boolean): void {
  try {
    window.localStorage.setItem(SHOWN_KEY, shown ? "1" : "0");
  } catch {
    // Remembering is a convenience; the toggle still works without it.
  }
}

function outcomeTone(outcome: string): string {
  if (outcome === "resolved" || outcome === "converged") return "var(--green)";
  if (outcome === "rejected") return "var(--yellow)";
  return "var(--accent)";
}

/** One step taken, as the trace line reads it. */
function TraceRow({ entry }: { entry: FlowTraceEntry }) {
  const who = entry.asked?.join(", ") ?? "";
  // A pick says what it picked and how that went, a count or the shared
  // summary what it found; a second asking says so.
  const picked = entry.select;
  const stance = picked
    ? `${picked.pick ?? "nothing"} · ${picked.outcome}`
    : entry.tally
      ? tallySummary(entry.tally)
      : entry.lock
        ? lockSummary(entry.lock)
        : entry.again
          ? "asked again"
          : (entry.stance ?? (entry.asked?.length ? "no stance" : ""));
  const good =
    entry.stance === "accept" || picked?.outcome === "feasible" || (entry.lock?.outcome === "locked" && entry.lock.saved);
  const bad =
    entry.stance === "reject" ||
    (picked && picked.outcome !== "feasible") ||
    entry.tally?.outcome === "empty" ||
    (entry.lock && !(entry.lock.outcome === "locked" && entry.lock.saved));
  const stanceTone = good ? "var(--green)" : bad ? "var(--yellow)" : "var(--muted-foreground)";
  return (
    <div className="flex items-baseline gap-2 border-b border-border/60 py-1 last:border-b-0 font-mono text-micro">
      <span className="w-4 text-right tabular text-faint">{entry.turn}</span>
      <span className="text-text">{entry.step}</span>
      {who && <span className="truncate text-muted-foreground">{who}</span>}
      {stance && <span style={{ color: stanceTone }}>{stance}</span>}
      {entry.next && <span className="text-faint">→ {entry.next}</span>}
    </div>
  );
}

/** The memory key a run's record is filed under. */
function recordKey(episode: EpisodeSummary): string {
  return `log/episodes/${episode.short_id}`;
}

function RecordLink({
  episode,
  onOpenMemory,
  label,
}: {
  episode: EpisodeSummary;
  onOpenMemory?: (key: string) => void;
  label: string;
}) {
  const key = recordKey(episode);
  const text = (
    <>
      {label} <span className="font-mono text-text">{episode.short_id}</span>
    </>
  );
  if (!onOpenMemory) return <span>{text}</span>;
  return (
    <button type="button" onClick={() => onOpenMemory(key)} className="rounded hover:text-text hover:underline" title={key}>
      {text}
    </button>
  );
}

export function FlowPanel({
  episode,
  floor,
  earlier = [],
  onOpenMemory,
}: {
  episode: EpisodeSummary;
  floor: RoomFloor | null;
  /** Runs this thread held before the one shown, newest first. */
  earlier?: EpisodeSummary[];
  /** Opens a run's record, the `log/episodes/<id>` memory. */
  onOpenMemory?: (key: string) => void;
}) {
  const [shown, setShown] = useState(readShown);
  const flow = episode.flow;
  if (!flow) return null;
  const trace = episode.trace ?? [];
  const open = episode.outcome === "open";
  const speakers = floor?.speakers ?? [];
  const toggle = () => {
    setShown(s => !s);
    writeShown(!shown);
  };
  const Chevron = shown ? ChevronDown : ChevronRight;
  return (
    <div className={shown ? "px-4 py-3" : "border-b border-border px-4 py-2"} data-testid="flow-panel">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={shown}
        title={shown ? "Hide the flow" : "Show the flow"}
        className={`-mx-1 flex w-[calc(100%+0.5rem)] min-w-0 items-baseline gap-x-2 overflow-hidden whitespace-nowrap rounded px-1 text-left transition-colors hover:bg-hairline ${shown ? "mb-2" : ""}`}
      >
        <Chevron className="size-3 self-center text-faint" />
        <span className="text-micro font-medium text-faint">Flow</span>
        <span className="font-mono text-micro text-text">{flow.name}</span>
        <span className="text-micro" style={{ color: outcomeTone(episode.outcome) }}>
          {open ? `at ${episode.current_step ?? flow.steps[0]?.id ?? "start"}` : episode.outcome}
        </span>
        {open && speakers.length > 0 && (
          <span className="text-micro" style={{ color: "var(--accent)" }}>
            {speakers.map((h) => `@${h}`).join(", ")} {speakers.length === 1 ? "has" : "have"} the floor
          </span>
        )}
        {open && floor && speakers.length === 0 && (
          <span className="text-micro text-muted-foreground">@{floor.holder} holds the floor</span>
        )}
        {!shown && trace.length > 0 && (
          <span className="ml-auto shrink-0 pl-2 text-micro text-faint">
            {trace.length} {trace.length === 1 ? "step" : "steps"} taken
          </span>
        )}
      </button>
      {shown && (
        <>
      {flow.ask && <div className="mb-2 text-label text-muted-foreground">{flow.ask}</div>}
      <div className="overflow-x-auto">
        <FlowGraph
          flow={flow}
          trace={trace}
          currentStep={episode.current_step}
          outcome={episode.outcome}
          floor={floor}
        />
      </div>
      {trace.length > 0 && (
        <div className="mt-2">
          {trace.map((entry, i) => <TraceRow key={i} entry={entry} />)}
        </div>
      )}
      {/* The record is the run: where the flow and the trace are filed, and
          the way back to a run this thread held before this one. */}
      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-micro text-muted-foreground">
        <RecordLink episode={episode} onOpenMemory={onOpenMemory} label="record" />
        {earlier.length > 0 && (
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span>earlier {earlier.length === 1 ? "run" : "runs"}</span>
            {earlier.map((run) => (
              <RecordLink key={run.short_id} episode={run} onOpenMemory={onOpenMemory} label={`${run.flow?.name ?? "run"} · ${run.outcome}`} />
            ))}
          </span>
        )}
      </div>
        </>
      )}
    </div>
  );
}
