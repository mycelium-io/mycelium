// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import type { ReactNode } from "react";

interface StatRowProps {
  label: string;
  value: ReactNode;
  dim?: boolean;
}

export function StatRow({ label, value, dim }: StatRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-0.5">
      <span className="text-micro text-muted truncate">{label}</span>
      <span className={`text-micro tabular font-semibold ${dim ? "text-dim" : "text-text"}`}>
        {value}
      </span>
    </div>
  );
}

interface MetricCardProps {
  title: string;
  children: ReactNode;
  accent?: "default" | "green" | "yellow" | "red";
}

export function MetricCard({ title, children, accent = "default" }: MetricCardProps) {
  const accentBorder =
    accent === "green"
      ? "border-l-green"
      : accent === "yellow"
        ? "border-l-yellow"
        : accent === "red"
          ? "border-l-[#f87171]"
          : "border-l-border2";

  return (
    <div className={`border border-border bg-paper p-4 border-l-2 ${accentBorder}`}>
      <h3 className="caps-mono-sm text-muted mb-3">{title}</h3>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export function fmt(n: number | undefined | null): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}k`;
  return new Intl.NumberFormat("en-US").format(n);
}

export function fmtUsd(n: number | undefined | null): string {
  if (n == null) return "—";
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function fmtDuration(startIso: string | undefined, endIso?: string): string {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  if (Number.isNaN(start)) return "—";
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const sec = Math.floor((end - start) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}
