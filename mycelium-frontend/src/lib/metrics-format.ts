// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n === 0) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 10_000) return (n / 1_000).toFixed(1) + "k";
  if (n >= 1_000) return n.toLocaleString("en-US");
  return String(n);
}

export function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n === 0) return "$0.00";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

export function fmtMs(n: number | null | undefined): string {
  if (n == null || n === 0) return "—";
  if (n < 10) return n.toFixed(1) + "ms";
  if (n < 1000) return Math.round(n) + "ms";
  return (n / 1000).toFixed(1) + "s";
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return sec + "s ago";
  const m = Math.floor(sec / 60);
  if (m < 60) return m + "m ago";
  const h = Math.floor(m / 60);
  return h + "h " + (m % 60) + "m ago";
}

export function fmtDur(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return sec + "s";
  const m = Math.floor(sec / 60);
  if (m < 60) return m + "m " + (sec % 60) + "s";
  const h = Math.floor(m / 60);
  return h + "h " + (m % 60) + "m";
}

export function statusKind(code: string): "ok" | "warn" | "err" {
  const c = parseInt(code, 10);
  if (c === 0) return "err";
  if (c >= 500) return "err";
  if (c >= 400) return "warn";
  return "ok";
}

export interface ErrorRateStats {
  rate: number;
  total: number;
  errors: number;
}

export function errorRate(cfn: Record<string, number> | undefined): ErrorRateStats {
  if (!cfn) return { rate: 0, total: 0, errors: 0 };
  let total = 0;
  let errors = 0;
  for (const [k, v] of Object.entries(cfn)) {
    if (!k.startsWith("status.")) continue;
    total += v;
    const kind = statusKind(k.replace("status.", ""));
    if (kind !== "ok") errors += v;
  }
  return { rate: total > 0 ? errors / total : 0, total, errors };
}

export interface BackendHistogram {
  count: number;
  sum: number;
  min: number;
  max: number;
}

export function histAvg(h: BackendHistogram | undefined): number {
  if (!h || !h.count) return 0;
  return h.sum / h.count;
}
