// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

interface IngestEvent {
  timestamp: string;
  mas_id: string;
  agent_id: string;
  state: string;
  room: string;
  payload_bytes: number;
  response_id: string | null;
  error: string | null;
  duration_ms: number;
}

interface IngestLogData {
  events: IngestEvent[];
  count: number;
}

interface IngestLogPanelProps {
  data: unknown;
}

export function IngestLogPanel({ data }: IngestLogPanelProps) {
  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p className="mb-2">No ingest log data available</p>
        <p className="text-micro text-dim">Knowledge ingestion events will appear here when CFN processes shared memories</p>
      </div>
    );
  }

  const log = data as IngestLogData;
  const events = log.events || [];

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p>No ingestion events recorded</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {/* Header */}
      <div className="grid grid-cols-[160px_1fr_120px_80px_80px_80px] gap-2 px-5 py-2 border-b border-border bg-surface/40 text-micro text-muted caps-mono-sm sticky top-0">
        <span>Time</span>
        <span>Room</span>
        <span>Agent</span>
        <span>State</span>
        <span>Size</span>
        <span className="text-right">Duration</span>
      </div>

      {events.map((e, idx) => (
        <div
          key={idx}
          className="grid grid-cols-[160px_1fr_120px_80px_80px_80px] gap-2 px-5 py-2.5 border-b border-border hover:bg-surface/40 transition-colors items-center"
        >
          <span className="text-micro text-dim tabular">{fmtTime(e.timestamp)}</span>
          <span className="text-micro text-text font-mono truncate">{e.room}</span>
          <span className="text-micro text-accent truncate">{e.agent_id}</span>
          <StateBadge state={e.state} />
          <span className="text-micro text-dim tabular">{fmtBytes(e.payload_bytes)}</span>
          <span className="text-micro text-text tabular text-right">{fmtMs(e.duration_ms)}</span>
        </div>
      ))}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    ok: "text-green-400",
    success: "text-green-400",
    error: "text-red-400",
    failed: "text-red-400",
    deduped: "text-yellow-400",
    disabled: "text-dim",
    skipped: "text-dim",
  };
  return <span className={`text-micro font-semibold ${colors[state] || "text-dim"}`}>{state}</span>;
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      hour12: false, month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function fmtBytes(b: number): string {
  if (b < 1024) return `${b}B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)}KB`;
  return `${(b / 1048576).toFixed(1)}MB`;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
