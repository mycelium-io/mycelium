// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The hints drawn over a text input that has a grammar: what the word being
 * typed can be, and the shape of what is being written with the part under the
 * cursor lit. The chat composer draws them for `@`, `[[`, `/` and commands; the
 * channel's find bar draws the same two for its `field:value` search, so a
 * person who has learned one has learned both.
 */

import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";

/** A normalized popover row, so rendering is uniform across every source. */
export interface Candidate {
  /** Stable React key. */
  id: string;
  /** The full token written into the input on select, e.g. `@bob`, `[[decisions/db]]`, `from:avery`. */
  insert: string;
  /** Part of a word (a folder, a field name): inserted without the trailing space, so completing goes on. */
  open?: boolean;
  /** Monospace accent label (the token itself), or a person's name. */
  primary: string;
  /** The label is a person's name, set as text rather than as a token. */
  named?: boolean;
  /** Dim qualifier (adapter, "memory", "skill"). */
  secondary: string;
  /** Optional trailing description. */
  tertiary?: string;
}

/**
 * One grid for every row, so the names share a column and what each does
 * starts at the same place whatever the name's length; the kind (command,
 * skill, the argument) sits quietly at the right edge, and only when the rows
 * differ in it — five rows all saying "command" is noise.
 */
export function CandidateList({
  candidates,
  highlight,
  onPick,
  onHover,
  label,
}: {
  candidates: Candidate[];
  highlight: number;
  onPick: (candidate: Candidate) => void;
  onHover: (index: number) => void;
  label?: string;
}) {
  const mixedKinds = new Set(candidates.map((c) => c.secondary)).size > 1;
  return (
    <div
      aria-label={label}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-xl border border-border bg-elevated p-1 shadow-xl"
    >
      {candidates.map((c, i) => (
        <button
          key={c.id}
          type="button"
          onMouseDown={(e) => {
            // mouseDown so the input keeps focus through the click
            e.preventDefault();
            onPick(c);
          }}
          onMouseEnter={() => onHover(i)}
          className={cn(
            "col-span-full grid grid-cols-subgrid items-baseline gap-x-3 rounded-lg px-2.5 py-1.5 text-left transition-colors",
            i === highlight ? "bg-surface" : "hover:bg-surface/60",
          )}
        >
          <span className={cn("max-w-56 truncate text-label", c.named ? "text-text" : "font-mono text-accent")}>
            {c.primary}
          </span>
          <span className="min-w-0 truncate text-micro text-muted-foreground">{c.tertiary}</span>
          <span className="max-w-40 truncate text-right text-micro text-muted-foreground/70">
            {mixedKinds && c.secondary}
          </span>
        </button>
      ))}
    </div>
  );
}

export interface Slot {
  label: string;
  filled: boolean;
}

/**
 * What's being written, drawn over the box: its head (`/agent`, `@conductor`,
 * `from:`), then each part, the one the cursor is in lit, and a line saying
 * what that part is. A warning says what will happen that the writer may not
 * expect.
 */
export function Signature({
  label,
  head,
  slots,
  active,
  about,
  completes,
  warning,
}: {
  label: string;
  head: string;
  slots: Slot[];
  active: number | null;
  about: string;
  completes: boolean;
  warning?: string | null;
}) {
  return (
    <div aria-label={label} className="rounded-lg border border-border bg-elevated px-2.5 py-1.5 shadow-lg">
      <div className="flex flex-wrap items-baseline gap-x-1 font-mono text-label">
        <span className="text-accent">{head}</span>
        {slots.map((s, i) => (
          <span
            key={`${s.label}-${i}`}
            aria-current={i === active || undefined}
            className={cn(
              "rounded px-1 transition-colors",
              i === active ? "bg-accent-soft text-accent" : s.filled ? "text-text" : "text-muted-foreground",
            )}
          >
            {s.label}
          </span>
        ))}
      </div>
      <p className="mt-0.5 flex items-center gap-1.5 text-micro text-muted-foreground">
        <span className="min-w-0">{about}</span>
        {completes && (
          <span className="ml-auto flex shrink-0 items-center gap-1">
            <Kbd size="xs" tone="muted">tab</Kbd> completes
          </span>
        )}
      </p>
      {warning && <p className="mt-1 text-micro text-yellow">{warning}</p>}
    </div>
  );
}
