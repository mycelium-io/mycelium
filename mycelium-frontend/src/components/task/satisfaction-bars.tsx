// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, type ReactNode } from "react";
import { percent } from "@/lib/conductor-line";

export interface SatisfactionRow {
  key: string;
  /** Whose satisfaction, or which option's: a handle, or a letter and its name. */
  label: ReactNode;
  /** 0-1, from the bad outcome to the ideal; undefined when no rating was given. */
  placed: number | undefined;
  why?: string;
}

/**
 * How satisfied, as bars: each row's bar runs from the member's bad outcome
 * (empty) to its own ideal (full), with the bar the pick has to clear drawn as
 * a line down all of them. A bar short of it is drawn in yellow. Each bar ends
 * in its percentage, and the reason sits beside it.
 */
export function SatisfactionBars({
  rows,
  bar,
  label,
  showBar = false,
  narrow = false,
}: {
  rows: SatisfactionRow[];
  /** The line every bar is measured against, 0-1; none drawn without one. */
  bar?: number;
  label: string;
  /** Name the line once, over the bars ("bar 60%"). */
  showBar?: boolean;
  /** Labels are a letter each, not a handle. */
  narrow?: boolean;
}) {
  const labelWidth = narrow ? "w-3" : "w-20";
  return (
    <ul className="space-y-1 text-micro" aria-label={label}>
      {showBar && bar !== undefined && (
        <li aria-hidden className="flex gap-2 leading-none">
          <span className={`${labelWidth} flex-shrink-0`} />
          <span className="relative h-3 w-24 flex-shrink-0">
            <span
              className="absolute bottom-0 -translate-x-1/2 whitespace-nowrap text-[10px] text-faint"
              style={{ left: `${bar * 100}%` }}
            >
              bar {percent(bar)}
            </span>
          </span>
        </li>
      )}
      {rows.map((r) => {
        const short = r.placed !== undefined && bar !== undefined && r.placed < bar;
        return (
          <li key={r.key} className="flex items-baseline gap-2">
            <span className={`${labelWidth} flex-shrink-0 truncate font-medium text-text`}>{r.label}</span>
            <span
              role="meter"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={r.placed === undefined ? undefined : Math.round(r.placed * 100)}
              aria-label={r.placed === undefined ? "no rating" : percent(r.placed)}
              title={r.placed === undefined ? "No rating" : `${percent(r.placed)} of the way to their ideal`}
              className="relative h-1.5 w-24 flex-shrink-0 self-center rounded-full bg-hairline"
            >
              {r.placed !== undefined && (
                <span
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{
                    width: `${Math.max(2, Math.min(100, r.placed * 100))}%`,
                    background: short ? "var(--yellow)" : "var(--accent)",
                  }}
                />
              )}
              {bar !== undefined && (
                <span
                  aria-hidden
                  className="absolute -inset-y-1 w-px bg-muted-foreground"
                  style={{ left: `${bar * 100}%` }}
                />
              )}
            </span>
            <span
              aria-hidden
              className="w-8 flex-shrink-0 tabular text-right"
              style={{ color: short ? "var(--yellow)" : "var(--muted-foreground)" }}
            >
              {r.placed === undefined ? "" : percent(r.placed)}
            </span>
            <span
              title={r.why}
              className={`min-w-0 line-clamp-2 ${r.placed === undefined ? "text-faint" : "text-muted-foreground"}`}
            >
              {r.placed === undefined ? "no rating" : (r.why ?? "")}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The options a run weighed, once, each by its letter: one line of its text,
 * the whole of it on a click. The one picked is marked. Bars elsewhere name
 * an option by its letter alone, so this is where a letter is read.
 */
export function OptionList({
  options,
  picked,
}: {
  options: { letter: string; text: string }[];
  picked?: string;
}) {
  return (
    <ul className="space-y-0.5 text-micro" aria-label="Options">
      {options.map((o) => (
        <OptionLine key={o.letter} letter={o.letter} text={o.text} picked={o.letter === picked} />
      ))}
    </ul>
  );
}

function OptionLine({ letter, text, picked }: { letter: string; text: string; picked: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={open ? undefined : text}
        className="flex w-full min-w-0 gap-2 rounded text-left transition-colors hover:bg-hairline"
      >
        <span className={`w-3 flex-shrink-0 font-mono ${picked ? "font-semibold text-accent" : "text-text"}`}>
          {letter}
        </span>
        <span className={`min-w-0 ${open ? "whitespace-pre-line" : "truncate"} ${picked ? "text-text" : "text-muted-foreground"}`}>
          {text}
        </span>
      </button>
    </li>
  );
}
