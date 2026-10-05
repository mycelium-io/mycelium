// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { createContext, useContext, useEffect, useState } from "react";

/** "now", "2m ago", "3h ago", "yesterday", "4d ago", then the date. */
export function relativeTime(at: number, now: number): string {
  if (!at) return "";
  const min = Math.floor(Math.max(0, now - at) / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** The exact time, for a hover: "Oct 4, 17:22". */
export function exactTime(at: number): string {
  if (!at) return "";
  return new Date(at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const NowContext = createContext<number | null>(null);

/** One clock for a whole list, so every "2m ago" in it moves together. */
export function NowProvider({ everyMs = 30_000, children }: { everyMs?: number; children: React.ReactNode }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return <NowContext.Provider value={now}>{children}</NowContext.Provider>;
}

/** The time a relative stamp is measured from: the provider's, else this render's. */
export function useNow(): number {
  const shared = useContext(NowContext);
  const [own] = useState(() => Date.now());
  return shared ?? own;
}

/** A relative timestamp that shows the exact time on hover.
 *  `unlessSameAs` hides it when that stamp reads the same, for a run of rows. */
export function Ago({
  at,
  unlessSameAs,
  className,
}: {
  at: string | number;
  unlessSameAs?: string | number;
  className?: string;
}) {
  const now = useNow();
  const ms = typeof at === "number" ? at : Date.parse(at) || 0;
  if (!ms) return null;
  if (unlessSameAs !== undefined) {
    const prev = typeof unlessSameAs === "number" ? unlessSameAs : Date.parse(unlessSameAs) || 0;
    if (prev && relativeTime(prev, now) === relativeTime(ms, now)) return <span className={className} />;
  }
  return (
    <time dateTime={new Date(ms).toISOString()} title={exactTime(ms)} className={className}>
      {relativeTime(ms, now)}
    </time>
  );
}
