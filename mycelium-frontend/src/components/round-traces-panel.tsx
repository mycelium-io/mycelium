// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";

interface RoundTrace {
  room: string;
  session_id: string;
  round_n: number;
  n_agents: number;
  elapsed_ms: number;
  decision_path: string;
  outcome: string;
  cfn_status: string | null;
  cfn_decide_ms: number | null;
  started_at: string;
  per_agent: Record<string, {
    first_response_ms: number | null;
    reply_action: string | null;
    was_synthesised: boolean;
  }>;
}

interface RoundTracesPanelProps {
  traces: unknown[] | null;
}

export function RoundTracesPanel({ traces }: RoundTracesPanelProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  if (traces === null) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p className="mb-2">No coordination round data available</p>
        <p className="text-micro text-dim">Round traces appear when agents negotiate via CFN</p>
      </div>
    );
  }

  const rounds = traces as RoundTrace[];
  const reversed = [...rounds].reverse();

  if (reversed.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p>No coordination rounds recorded yet</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {/* Header */}
      <div className="grid grid-cols-[80px_1fr_80px_80px_100px_100px_80px] gap-2 px-5 py-2 border-b border-border bg-surface/40 text-micro text-muted caps-mono-sm sticky top-0">
        <span>Round</span>
        <span>Session</span>
        <span>Agents</span>
        <span>Path</span>
        <span>Outcome</span>
        <span>CFN Status</span>
        <span className="text-right">Duration</span>
      </div>

      {reversed.map((r, idx) => (
        <div key={idx} className="border-b border-border">
          <button
            onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
            className="grid grid-cols-[80px_1fr_80px_80px_100px_100px_80px] gap-2 w-full px-5 py-2.5 text-left hover:bg-surface/40 transition-colors items-center"
          >
            <span className="text-micro text-text tabular">R{r.round_n}</span>
            <span className="text-micro text-dim truncate font-mono">{r.session_id}</span>
            <span className="text-micro text-text tabular">{r.n_agents}</span>
            <PathBadge path={r.decision_path} />
            <OutcomeBadge outcome={r.outcome} />
            <span className="text-micro text-dim">{r.cfn_status ?? "—"}</span>
            <span className="text-micro text-text tabular text-right">{fmtMs(r.elapsed_ms)}</span>
          </button>

          {expandedIdx === idx && (
            <div className="px-5 py-3 bg-bg border-t border-border">
              <div className="grid grid-cols-2 gap-4 mb-3">
                <div>
                  <span className="caps-mono-sm text-muted block mb-1">Room</span>
                  <span className="text-micro text-text font-mono">{r.room}</span>
                </div>
                <div>
                  <span className="caps-mono-sm text-muted block mb-1">Started</span>
                  <span className="text-micro text-text">{fmtTime(r.started_at)}</span>
                </div>
                {r.cfn_decide_ms != null && (
                  <div>
                    <span className="caps-mono-sm text-muted block mb-1">CFN /decide</span>
                    <span className="text-micro text-text tabular">{fmtMs(r.cfn_decide_ms)}</span>
                  </div>
                )}
              </div>

              <span className="caps-mono-sm text-muted block mb-2">Per Agent</span>
              <div className="space-y-1">
                {Object.entries(r.per_agent || {}).map(([handle, a]) => (
                  <div key={handle} className="flex items-center gap-3 text-micro">
                    <span className="text-accent w-[160px] truncate">{handle}</span>
                    <span className="text-text tabular w-[80px]">
                      {a.first_response_ms != null ? fmtMs(a.first_response_ms) : <span className="text-red-400">no reply</span>}
                    </span>
                    <ActionBadge action={a.reply_action} />
                    {a.was_synthesised && <span className="text-yellow-400 text-micro">(synthesised)</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function PathBadge({ path }: { path: string }) {
  const colors: Record<string, string> = {
    all_replied: "text-green-400",
    aborted: "text-red-400",
    synthesised: "text-yellow-400",
    partial: "text-amber-400",
  };
  return <span className={`text-micro ${colors[path] || "text-dim"}`}>{path}</span>;
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    agreed: "text-green-400",
    ongoing: "text-blue-400",
    error: "text-red-400",
    timeout: "text-yellow-400",
    deadlocked: "text-red-400",
  };
  return <span className={`text-micro font-semibold ${colors[outcome] || "text-dim"}`}>{outcome}</span>;
}

function ActionBadge({ action }: { action: string | null }) {
  if (!action) return <span className="text-micro text-dim">—</span>;
  const colors: Record<string, string> = {
    accept: "text-green-400",
    reject: "text-red-400",
    counter_offer: "text-amber-400",
  };
  return <span className={`text-micro ${colors[action] || "text-dim"}`}>{action}</span>;
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60000);
  const sec = Math.floor((ms % 60000) / 1000);
  return `${min}m${sec}s`;
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
