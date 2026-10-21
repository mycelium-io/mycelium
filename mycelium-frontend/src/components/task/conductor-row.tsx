// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronRight, Workflow } from "lucide-react";
import {
  isSuccess,
  lockSummary,
  midSentence,
  pickSummary,
  placedOf,
  stepVerb,
  tallySummary,
  views,
  type ConductorLine,
  type PickRecord,
} from "@/lib/conductor-line";
import { MessageBody } from "@/components/message-body";
import { MemoryKeyLink } from "@/components/markdown-content";

interface Props {
  line: ConductorLine;
  /** The post's prose: the prompt a member was given, kept behind a toggle. */
  text: string;
  onOpenMemory?: (key: string) => void;
  /** A turn put to several members at once: everyone it went to, drawn as one row. */
  members?: string[];
}

function Handle({ children }: { children: string }) {
  return <span className="font-medium text-text">{children}</span>;
}

/** Where a run saved what it settled to, as a link to the memory, or that it
 *  could not be saved (`null`). Nothing when the run saved nothing. It never
 *  shrinks: the row wraps it under the summary instead. */
function Saved({ memory, onOpenMemory }: { memory: string | null | undefined; onOpenMemory?: (key: string) => void }) {
  if (memory === undefined) return null;
  if (memory === null) return <span className="flex-shrink-0 text-faint">could not be saved</span>;
  return (
    // In a thread too narrow even for the key, it breaks across lines rather
    // than being cut, so it can still be read whole.
    <span className="flex min-w-0 max-w-full flex-shrink-0 items-baseline gap-1 text-faint [overflow-wrap:anywhere] [&>*]:min-w-0 [&>*]:max-w-full">
      <span className="flex-shrink-0">saved as</span>
      <MemoryKeyLink memoryKey={memory} onClick={onOpenMemory} />
    </span>
  );
}

/**
 * One conductor post, drawn from its structured line rather than its prose.
 *
 * The prose is what the members read — the whole prompt, the check-ins so far —
 * and in a thread it reads as the conductor talking over the members. So a
 * turn is one line naming the step and who it went to, with the prompt a click
 * away, and the opening and the end are one line each.
 */
export function ConductorRow({ line, text, onOpenMemory, members }: Props) {
  const [open, setOpen] = useState(false);
  const expandable = line.event === "turn" || line.event === "open";

  let body: React.ReactNode;
  // Where the run saved its result, drawn beside the line rather than inside
  // it, so a narrow thread cuts the summary and never the link to it.
  let saved: string | null | undefined;
  switch (line.event) {
    case "open":
      body = (
        <>
          <span>Running</span> <span className="font-medium text-accent">{line.protocol}</span>
          {Object.entries(line.roles).map(([role, who]) => (
            <span key={role}>
              {" · "}
              <Handle>{who}</Handle> as {role}
            </span>
          ))}
          {line.members.length > 0 && (
            <span>
              {" · "}
              {line.members.map((m, i) => (
                <span key={m}>
                  {i > 0 && ", "}
                  <Handle>{m}</Handle>
                </span>
              ))}
            </span>
          )}
        </>
      );
      break;
    case "turn": {
      const who = members ?? [line.to];
      // Concord's and accord's steps say what the members are doing; any
      // other flow names its step and who it went to.
      const verb = stepVerb(line.protocol, line.step, who.length);
      body = verb ? (
        <>
          {who.map((m, i) => (
            <span key={m}>
              {i > 0 && (i === who.length - 1 ? " and " : ", ")}
              <Handle>{m}</Handle>
            </span>
          ))}
          <span> {verb}</span>
          {line.again && <span className="text-faint"> (asked again)</span>}
        </>
      ) : (
        <>
          <span className="font-medium text-accent">{line.step}</span>
          <span> {line.tell ? "told" : "→"} </span>
          {who.map((m, i) => (
            <span key={m}>
              {i > 0 && ", "}
              <Handle>{m}</Handle>
            </span>
          ))}
          {line.again && <span className="text-faint"> (asked again)</span>}
          <span className="text-faint">
            {" · "}turn {line.turn} of {line.cap}
            {line.rounds ? ` · round ${line.round} of ${line.rounds}` : ""}
          </span>
        </>
      );
      break;
    }
    case "edge": {
      const said =
        line.stance === "accept"
          ? "accepted"
          : line.stance === "reject"
            ? "blocked"
            : line.stance === "silent"
              ? "did not answer"
              : "stated no stance";
      body = (
        <>
          <span className="font-medium text-accent">{line.step}</span>
          <span>: </span>
          <Handle>{line.who}</Handle>
          <span> {said}, on to </span>
          <span className="font-medium text-accent">{line.next}</span>
        </>
      );
      break;
    }
    case "select":
      body = line.select.pick ? (
        <>
          <span className="font-medium text-accent">Picked</span> <span>{pickSummary(line.select)}</span>
        </>
      ) : (
        <span>{pickSummary(line.select)}</span>
      );
      break;
    case "tally":
      body = <span>{tallySummary(line.tally)}</span>;
      break;
    case "lock":
      body = <span>{lockSummary(line.lock)}</span>;
      saved = line.lock.outcome !== "locked" ? undefined : line.lock.saved ? line.lock.memory : null;
      break;
    case "close": {
      const good = isSuccess(line.outcome);
      // A run that picked says what it went with, or that it couldn't get there.
      const said = line.pick
        ? line.outcome === "converged"
          ? `Everyone meets the bar: going with ${line.pick}`
          : line.outcome === "resolved"
            ? `Best found, below the bar for some: ${line.pick}`
            : `Couldn't get everyone there. Best was ${line.pick}`
        : `${line.protocol} ${good ? "done" : line.outcome}`;
      body = (
        <>
          <span className="font-medium" style={{ color: good ? "var(--green)" : "var(--yellow)" }}>
            {good ? "✓" : "✗"} {said}
          </span>
          {line.pick && line.text ? (
            <span className="text-text">: {line.text}</span>
          ) : (
            <span className="text-faint">
              {" · "}
              {line.steps} step{line.steps === 1 ? "" : "s"}
              {!good && line.reason ? ` · ${line.reason}` : ""}
            </span>
          )}
        </>
      );
      saved = line.memory;
      break;
    }
  }

  return (
    <div data-testid="conductor-row" className="px-5 py-1">
      <div className="flex items-start gap-2 text-micro text-muted-foreground">
        <span className="flex h-[1lh] w-7 flex-shrink-0 items-center justify-center" aria-hidden>
          <Workflow className="size-3.5" />
        </span>
        {/* The summary at its full width first; where it and the saved key
            don't both fit, the key drops to a line of its own, whole, since
            it's what people click and look for later in Memory. */}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2">
          <span className="min-w-0 flex-auto truncate">{body}</span>
          <Saved memory={saved} onOpenMemory={onOpenMemory} />
        </div>
        {expandable && text.trim() && (
          <button
            type="button"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            className="flex flex-shrink-0 items-center gap-0.5 rounded px-1 text-faint transition-colors hover:text-text"
          >
            <ChevronRight className={`size-3 transition-transform ${open ? "rotate-90" : ""}`} />
            {line.event === "turn" ? "prompt" : "flow"}
          </button>
        )}
      </div>
      {open && (
        <div className="ml-9 mt-1 rounded-md border border-border px-3 py-2 text-muted-foreground">
          <MessageBody content={text} onOpenMemory={onOpenMemory} />
        </div>
      )}
      {line.event === "select" && <Scorecard record={line.select} />}
    </div>
  );
}

/**
 * A pick, reasons first: each member's view of the pick in words (what their
 * rating means against the bar, and why), with every option's numbers a click
 * away for anyone checking the arithmetic.
 */
export function Scorecard({ record }: { record: PickRecord }) {
  const [numbers, setNumbers] = useState(false);
  if (!record.pick) return null;
  return (
    <div className="ml-9 mt-1 text-micro">
      <ul className="space-y-0.5" aria-label={`How each member sees ${record.pick}`}>
        {views(record, record.pick).map((v) => (
          <li key={v.member} className="flex gap-2">
            <span className="w-20 flex-shrink-0 truncate font-medium text-text">{v.member}</span>
            <span className="min-w-0 text-muted-foreground">
              <span style={{ color: v.short ? "var(--yellow)" : undefined }}>{v.verdict}</span>
              {v.why && <span>, because {midSentence(v.why)}</span>}
            </span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => setNumbers((n) => !n)}
        aria-expanded={numbers}
        className="mt-0.5 flex items-center gap-0.5 rounded px-1 text-faint transition-colors hover:text-text"
      >
        <ChevronRight className={`size-3 transition-transform ${numbers ? "rotate-90" : ""}`} />
        numbers
      </button>
      {numbers && <Numbers record={record} />}
    </div>
  );
}

/**
 * Every option's ratings: options down the side, members across, each cell a
 * member's rating on its own scale with how far that is from its bad outcome
 * to its ideal, `?` where a member gave none, the pick marked, and anything
 * under the bar drawn so it shows. A cell's reason is its tooltip.
 */
function Numbers({ record }: { record: PickRecord }) {
  const bar = record.threshold;
  return (
    <div className="mt-1 overflow-x-auto">
      <table className="text-micro tabular" aria-label={`Ratings, bar ${bar}%`}>
        <thead>
          <tr className="text-faint">
            <th className="py-0.5 pr-3 text-left font-normal">option</th>
            {record.cast.map((h) => (
              <th key={h} className="px-2 py-0.5 text-right font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {record.options.map((o) => {
            const picked = o.label === record.pick;
            return (
              <tr key={o.label} className={picked ? "bg-accent-soft" : undefined}>
                <th
                  scope="row"
                  title={o.text}
                  // The thread pane is narrow and every member needs a column,
                  // so an option's text gives way; the whole of it is the tooltip.
                  className="max-w-[9rem] truncate py-0.5 pr-3 text-left font-normal text-muted-foreground"
                >
                  <span className={`font-mono ${picked ? "font-semibold text-accent" : "text-text"}`}>{o.label}</span>{" "}
                  {o.text}
                </th>
                {record.cast.map((h) => {
                  const r = record.table[o.label]?.[h];
                  const at = placedOf(record, o.label, h);
                  const short = at !== undefined && at * 100 < bar;
                  return (
                    <td
                      key={h}
                      title={record.reasons?.[o.label]?.[h]}
                      className="whitespace-nowrap px-2 py-0.5 text-right"
                      style={{ color: r === undefined ? "var(--faint)" : short ? "var(--yellow)" : "var(--text)" }}
                    >
                      {r === undefined ? "?" : `${r} (${Math.round((at ?? 0) * 100)}%)`}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-0.5 text-micro text-faint">
        Each rating is on the member&apos;s own scale; in brackets, how far it is from their bad outcome
        to their ideal. The bar is {bar}%.
      </p>
    </div>
  );
}
