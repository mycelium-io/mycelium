// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The pieces the Metrics page is drawn with, shared by its tabs: a label, a
 * titled panel divided by hairlines rather than boxed in a card, a row of
 * figures, and the notes that keep a figure honest.
 */

import type { ReactNode } from "react";

/** A small sentence-case label, as the rest of the app draws one. */
export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`text-micro font-medium text-faint ${className}`}>{children}</div>;
}

export function Dot({ color }: { color: string }) {
  return <span className="inline-block size-1.5 shrink-0 rounded-full" style={{ background: color }} />;
}

/** A titled section: a label over its figures, divided from the next by a
 *  hairline rather than boxed in a card. Every section of the page is one, so
 *  one with nothing to show still holds its place and explains itself. */
export function Panel({
  title,
  meta,
  children,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 overflow-hidden border-t border-border ${className}`}>
      <header className="flex h-8 items-center justify-between gap-3 px-4">
        <Label>{title}</Label>
        {meta && <div className="flex items-center gap-1.5 text-micro text-muted-foreground">{meta}</div>}
      </header>
      {children}
    </section>
  );
}

/** The line a panel shows instead of a grid of dashes: what is missing, and the
 *  thing that would fill it. */
export function Nothing({ children }: { children: ReactNode }) {
  return <p className="px-4 py-3 text-label leading-relaxed text-muted-foreground">{children}</p>;
}

/** One labeled figure inside a panel's grid. */
export function Figure({
  label,
  value,
  color,
  hint,
}: {
  label: string;
  value: ReactNode;
  color?: string;
  hint?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-4 py-1.5" title={hint}>
      <Label>{label}</Label>
      <span className="font-mono text-label tabular text-text" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

/** A responsive row of figures, spaced rather than boxed into cells. */
export function Figures({ children, cols = 4 }: { children: ReactNode; cols?: 3 | 4 | 5 | 6 }) {
  const wide = {
    3: "sm:grid-cols-3",
    4: "sm:grid-cols-4",
    5: "sm:grid-cols-5",
    6: "sm:grid-cols-3 lg:grid-cols-6",
  }[cols];
  return <div className={`grid grid-cols-2 pb-2 ${wide}`}>{children}</div>;
}

/** A footnote under a panel, the caveat that keeps a figure honest. */
export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-border px-4 py-2 text-micro leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}
