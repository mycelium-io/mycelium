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

import type { EpisodeSummary, FlowTraceEntry, RoomFloor } from "@/lib/api";
import { FlowGraph } from "@/components/flow-graph";

function outcomeTone(outcome: string): string {
  if (outcome === "resolved") return "var(--green)";
  if (outcome === "rejected") return "var(--yellow)";
  return "var(--accent)";
}

/** One step taken, as the trace line reads it. */
function TraceRow({ entry }: { entry: FlowTraceEntry }) {
  const who = entry.asked?.join(", ") ?? "";
  const stance = entry.stance ?? (entry.asked?.length ? "no stance" : "");
  const stanceTone =
    entry.stance === "accept" ? "var(--green)" : entry.stance === "reject" ? "var(--yellow)" : "var(--muted-foreground)";
  return (
    <div className="flex items-baseline gap-2 border-b border-border/60 py-1 last:border-b-0 font-mono text-micro">
      <span className="w-4 text-right tabular text-faint">{entry.turn}</span>
      <span className="text-text">{entry.step}</span>
      {who && <span className="truncate text-muted-foreground">{who}</span>}
      {stance && <span style={{ color: stanceTone }}>{stance}</span>}
      <span className="text-faint">→ {entry.next}</span>
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
  const flow = episode.flow;
  if (!flow) return null;
  const trace = episode.trace ?? [];
  const open = episode.outcome === "open";
  const speakers = floor?.speakers ?? [];
  return (
    <div className="px-4 py-3" data-testid="flow-panel">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-micro uppercase tracking-wide text-faint">Flow</span>
        <span className="font-mono text-micro text-text">{flow.name}</span>
        <span className="text-micro capitalize" style={{ color: outcomeTone(episode.outcome) }}>
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
      </div>
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
    </div>
  );
}
