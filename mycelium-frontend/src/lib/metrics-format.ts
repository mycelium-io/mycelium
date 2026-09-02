// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Formatting for the metrics screen: compact numbers, durations, and the
 * shape the backend reports a histogram in.
 *
 * Everything here is presentation only — nothing invents a value. A counter the
 * backend has never touched reads as `-`, not `0`, so "not measured" and
 * "measured, zero" stay distinguishable on the page.
 */

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n === 0) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 10_000) return (n / 1_000).toFixed(1) + "k";
  if (n >= 1_000) return n.toLocaleString("en-US");
  return String(n);
}

export function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n === 0) return "$0.00";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

export function fmtMs(n: number | null | undefined): string {
  if (n == null || n === 0) return "-";
  if (n < 10) return n.toFixed(1) + "ms";
  if (n < 1000) return Math.round(n) + "ms";
  return (n / 1000).toFixed(1) + "s";
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return sec + "s ago";
  const m = Math.floor(sec / 60);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h " + (m % 60) + "m ago";
  return Math.floor(h / 24) + "d ago";
}

export function fmtDur(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return sec + "s";
  const m = Math.floor(sec / 60);
  if (m < 60) return m + "m " + (sec % 60) + "s";
  const h = Math.floor(m / 60);
  if (h < 24) return h + "h " + (m % 60) + "m";
  return Math.floor(h / 24) + "d " + (h % 24) + "h";
}

/** A whole-number percentage, or `-` when the denominator is zero — a rate over
 *  nothing is undefined, not 0%. */
export function fmtPct(part: number | null | undefined, whole: number | null | undefined): string {
  if (!whole) return "-";
  return Math.round(100 * ((part ?? 0) / whole)) + "%";
}

/** The backend's histogram shape (`app/services/metrics.py`). `min`/`max` are
 *  null until the first sample lands. */
export interface BackendHistogram {
  count: number;
  sum: number;
  min: number | null;
  max: number | null;
}

export function histAvg(h: BackendHistogram | undefined): number {
  if (!h || !h.count) return 0;
  return h.sum / h.count;
}

/**
 * Counters filed under a dotted prefix, biggest first.
 *
 * The backend flattens dimensions into the key (`by_operation.task_compile`),
 * and files that dimension's own totals one level deeper
 * (`by_operation.task_compile.input_tokens`). Those deeper keys belong to the
 * same entry rather than being entries of their own, so they are dropped unless
 * `deep` is set — which callers use for a dimension whose values may legitimately
 * contain a dot (a model id like `openai/gpt-4.1`).
 */
export function subCounters(
  counters: Record<string, number> | undefined,
  prefix: string,
  deep = false,
): [string, number][] {
  if (!counters) return [];
  const head = prefix.endsWith(".") ? prefix : prefix + ".";
  return Object.entries(counters)
    .filter(([k]) => k.startsWith(head))
    .map(([k, v]) => [k.slice(head.length), v] as [string, number])
    .filter(([name]) => deep || !name.includes("."))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
