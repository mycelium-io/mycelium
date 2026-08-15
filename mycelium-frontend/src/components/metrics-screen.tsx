// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
//
// Metrics dashboard.
//
// Hierarchy: header band → 3 KPI plates → 3 latency strips → agent activity →
// 5 diagnostic tiles → secondary token strip → by-model table.
//
// Single accent. Errors are signalled with eyebrow text + italic helper rather
// than a second color. The page is built from these pieces:
//
//   <MetricsScreen />
//     ├─ <HeaderBand />          refresh control, pause, tick, collector chip
//     ├─ <KpiPlate />            big numeral + sub + sparkline (or disabled CTA)
//     ├─ <LatencyStrip />        n / avg / min / max for each backend histogram
//     ├─ <AgentActivityTable />  collector-only
//     ├─ <DiagTile />            quiet k/v rows with optional footer
//     ├─ <CfnStatusTile />       diag tile with dynamic HTTP-status rows
//     ├─ <ByModelTable />        collector-only spend breakdown
//     ├─ <CollectorOffPlate />   disabled mode (folded corner, exact CLI)
//     └─ <BackendDownPlate />    backend unreachable

"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import {
  fmtNum, fmtUsd, fmtMs, fmtAgo, fmtDur,
  statusKind, errorRate, histAvg,
  type BackendHistogram,
} from "@/lib/metrics-format";
import { fetchBackendMetrics, fetchCollectorMetrics, fetchHosts, type HostInfo } from "@/lib/api";

// ── Types (loose; backend payload is dynamic) ─────────────────────────────

interface BackendCounters {
  embeddings?: Record<string, number>;
  memory?: Record<string, number>;
  indexer?: Record<string, number>;
  coordination?: Record<string, number>;
  cfn?: Record<string, number>;
  cfn_llm?: Record<string, number>;
  llm?: Record<string, number>;
  knowledge?: Record<string, number>;
  synthesis?: Record<string, number>;
}

interface BackendMetrics {
  started_at?: string;
  updated_at?: string;
  counters?: BackendCounters;
  histograms?: Record<string, BackendHistogram>;
}

interface ByAgent {
  agent: string;
  tokens: number;
  cost: number;
  sessions: number;
  last: string;
}

interface ByModel {
  model: string;
  tokens_in: number;
  tokens_out: number;
  calls: number;
  cost_usd: number;
}

interface AgentTokens { input: number; output: number; cache_read: number; cache_write: number; total: number }
interface ModelTokens extends AgentTokens {}

interface CollectorMetrics {
  counters?: {
    cost_usd?: { total?: number; by_agent?: Record<string, number>; by_model?: Record<string, number> };
    tokens?: {
      total?: AgentTokens;
      by_agent?: Record<string, AgentTokens>;
      by_model?: Record<string, ModelTokens>;
    };
    messages?: { processed?: number; queued?: number };
    sessions_stuck?: number;
  };
  histograms?: {
    by_agent?: Record<string, { calls: number; last?: string }>;
    [k: string]: unknown;
  };
  sessions?: unknown[];
  spend_5m?: number[];
  err_5m?: number[];
}

function deriveAgents(c: CollectorMetrics): ByAgent[] {
  const tokensByAgent = c.counters?.tokens?.by_agent || {};
  const costByAgent = c.counters?.cost_usd?.by_agent || {};
  const histByAgent = (c.histograms?.by_agent as Record<string, { calls?: number; last?: string }>) || {};
  const names = new Set([
    ...Object.keys(tokensByAgent),
    ...Object.keys(costByAgent),
  ]);
  return [...names].map(agent => ({
    agent,
    tokens: tokensByAgent[agent]?.total ?? 0,
    cost: costByAgent[agent] ?? 0,
    sessions: histByAgent[agent]?.calls ?? 0,
    last: histByAgent[agent]?.last ?? "-",
  })).sort((a, b) => b.tokens - a.tokens);
}

function deriveModels(c: CollectorMetrics): ByModel[] {
  const tokensByModel = c.counters?.tokens?.by_model || {};
  const costByModel = c.counters?.cost_usd?.by_model || {};
  const names = new Set([
    ...Object.keys(tokensByModel),
    ...Object.keys(costByModel),
  ]);
  return [...names].map(model => ({
    model,
    tokens_in: tokensByModel[model]?.input ?? 0,
    tokens_out: tokensByModel[model]?.output ?? 0,
    calls: 0,
    cost_usd: costByModel[model] ?? 0,
  })).sort((a, b) => b.cost_usd - a.cost_usd);
}

// ── Atoms ─────────────────────────────────────────────────────────────────

function Caps({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`text-micro font-medium uppercase tracking-wide text-muted-foreground ${className}`}>{children}</div>;
}

function Sparkline({ values, width = 110, height = 30, dim = false }: {
  values?: number[]; width?: number; height?: number; dim?: boolean;
}) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values, 0.0001);
  const stride = width / (values.length - 1);
  const points = values.map((v, i) => `${i * stride},${height - (v / max) * height}`).join(" ");
  const areaPoints = `0,${height} ${points} ${width},${height}`;
  const stroke = dim ? "var(--muted-foreground)" : "var(--accent)";
  return (
    <svg width={width} height={height} className="block flex-shrink-0">
      <polygon points={areaPoints} fill={stroke} opacity="0.10" />
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="1.2" />
      <circle
        cx={(values.length - 1) * stride}
        cy={height - (values[values.length - 1] / max) * height}
        r="2"
        fill={stroke}
      />
    </svg>
  );
}

// ── Header band ────────────────────────────────────────────────────────────

function HeaderBand({
  backend, collectorOn, paused, setPaused, intervalSec, setIntervalSec,
}: {
  backend: BackendMetrics | null;
  collectorOn: boolean;
  paused: boolean;
  setPaused: (b: boolean) => void;
  intervalSec: number;
  setIntervalSec: (s: number) => void;
}) {
  return (
    <div className="flex h-[44px] flex-shrink-0 items-center gap-4 border-b border-border bg-paper px-5">
      <div className="font-mono text-micro text-muted-foreground">
        {backend ? (
          <>
            up <span className="text-text">{fmtDur(backend.started_at)}</span>
            <span className="mx-1.5 text-faint">·</span>
            updated <span className="text-text">{fmtAgo(backend.updated_at)}</span>
          </>
        ) : (
          <span className="text-yellow">backend unreachable</span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="text-micro text-faint">Every</span>
          <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
            {[5, 10, 30, 60].map(s => {
              const on = intervalSec === s;
              return (
                <button
                  key={s}
                  onClick={() => setIntervalSec(s)}
                  className={`rounded-md px-2 py-0.5 text-micro font-medium tabular transition-colors ${
                    on ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text"
                  }`}
                >
                  {s}s
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-stretch overflow-hidden rounded-lg border border-border">
          <button
            onClick={() => setPaused(!paused)}
            className={`flex items-center gap-1.5 border-r border-border px-2.5 text-micro font-medium transition-colors ${
              paused ? "text-muted-foreground hover:text-text" : "text-text"
            }`}
          >
            {paused ? (
              <>
                <Play className="size-3" />
                Paused
              </>
            ) : (
              <>
                <span className="inline-block size-1.5 rounded-full bg-accent" />
                Live
              </>
            )}
          </button>
          <CollectorChip on={collectorOn} />
        </div>
      </div>
    </div>
  );
}

function CollectorChip({ on }: { on: boolean }) {
  return (
    <div className="group relative flex items-center gap-1.5 px-2.5">
      <span className="inline-block size-1.5 rounded-full" style={{ background: on ? "var(--accent)" : "var(--faint)" }} />
      <span className="text-micro font-medium text-muted-foreground">
        Collector {on ? "on" : "off"}
      </span>
      {!on && (
        <div className="pointer-events-none absolute right-0 top-full z-10 mt-1.5 w-[280px] origin-top-right rounded-xl border border-border bg-elevated px-3.5 py-3 opacity-0 shadow-xl transition-opacity group-hover:opacity-100">
          <div className="text-micro font-medium uppercase tracking-wide text-muted-foreground">Collector off</div>
          <p className="mt-1.5 text-micro leading-relaxed text-muted-foreground">
            Cost, agent activity, and per-model breakdowns are not collected. Start the
            collector in another terminal to populate this section within 30s.
          </p>
          <div className="mt-2 rounded-lg border border-border bg-surface px-2.5 py-1.5 font-mono text-micro text-accent">
            mycelium metrics collect
          </div>
        </div>
      )}
    </div>
  );
}

// ── KPI plate ──────────────────────────────────────────────────────────────

function KpiPlate({
  label, value, sub, sparkline, disabled = false, alert = false, errorRatePct, cta,
}: {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  sparkline?: number[];
  disabled?: boolean;
  alert?: boolean;
  errorRatePct?: number;
  cta?: string;
}) {
  const valueColor = (() => {
    if (disabled) return "var(--faint)";
    if (errorRatePct != null && errorRatePct > 0) {
      // lerp from --text (#eaeaea) to red (#f87171) clamped at 20%
      const t = Math.min(errorRatePct / 20, 1);
      const r = Math.round(0xea + t * (0xf8 - 0xea));
      const g = Math.round(0xea + t * (0x71 - 0xea));
      const b = Math.round(0xea + t * (0x71 - 0xea));
      return `rgb(${r},${g},${b})`;
    }
    return "var(--text)";
  })();
  return (
    <div className="flex min-w-0 items-center gap-5 border-r border-border2 px-6 py-4 last:border-r-0">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Caps>{label}</Caps>
        <div
          className={`tabular ${alert ? "italic" : ""}`}
          style={{
            fontSize: "2rem",
            fontWeight: 700,
            lineHeight: 1.05,
            letterSpacing: "-0.01em",
            color: valueColor,
          }}
        >
          {value}
        </div>
        <div className="text-micro leading-snug text-muted-foreground tabular">{sub}</div>
        {disabled && cta && (
          <div className="font-mono text-micro text-accent">{cta}</div>
        )}
      </div>
      {!disabled && sparkline && (
        <div className="flex flex-shrink-0 items-end self-end pb-1">
          <Sparkline values={sparkline} />
        </div>
      )}
    </div>
  );
}

// ── Latency strip (one per histogram) ─────────────────────────────────────

function LatencyStrip({ name, h }: { name: string; h?: BackendHistogram }) {
  if (!h || !h.count) {
    return (
      <div className="border-r border-border px-5 py-3 last:border-r-0">
        <Caps>{name}</Caps>
        <div className="mt-1.5 text-micro italic text-faint">no samples</div>
      </div>
    );
  }
  const avg = histAvg(h);
  return (
    <div className="border-r border-border px-5 py-3 last:border-r-0">
      <div className="flex items-baseline justify-between">
        <Caps>{name}</Caps>
        <span className="font-mono text-micro text-faint">n={h.count}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-3 tabular">
        <Cell k="avg" v={fmtMs(avg)} />
        <Cell k="min" v={fmtMs(h.min)} />
        <Cell k="max" v={fmtMs(h.max)} />
      </div>
    </div>
  );
}

function Cell({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-micro text-faint">{k}</span>
      <span className="font-mono text-label font-semibold text-text">{v}</span>
    </div>
  );
}

// ── Diagnostic tile ────────────────────────────────────────────────────────

type DiagRow = [string, ReactNode, { dim?: boolean; alert?: boolean }?];

function DiagTile({ title, rows, footer, alert = false }: {
  title: string;
  rows: DiagRow[];
  footer?: ReactNode;
  alert?: boolean;
}) {
  return (
    <div className="flex flex-col border border-border2 bg-paper">
      <div className="flex items-baseline justify-between border-b border-border px-3.5 py-2">
        <Caps className={alert ? "text-accent" : ""}>{title}</Caps>
        {alert && <span className="font-mono text-micro italic text-accent">!</span>}
      </div>
      <div className="flex-1 px-3.5 py-2">
        {rows.map(([k, v, opts], i) => {
          const dim = opts?.dim;
          const a = opts?.alert;
          return (
            <div key={i} className="flex items-baseline justify-between gap-3 py-0.5">
              <span className="text-micro lowercase text-muted-foreground">{k}</span>
              <span className={`font-mono text-label font-semibold tabular ${
                a ? "italic text-accent" : dim ? "text-faint" : "text-text"
              }`}>
                {v}
              </span>
            </div>
          );
        })}
      </div>
      {footer && (
        <div className="border-t border-border px-3.5 py-1.5 text-micro italic text-faint">{footer}</div>
      )}
    </div>
  );
}

// ── CFN status tile ───────────────────────────────────────────────────────

function CfnStatusTile({ cfn }: { cfn?: Record<string, number> }) {
  const codes = Object.entries(cfn || {})
    .filter(([k]) => k.startsWith("status."))
    .map(([k, v]) => ({ code: k.replace("status.", ""), count: v }))
    .sort((a, b) => a.code.localeCompare(b.code));
  const hasErr = codes.some(c => statusKind(c.code) !== "ok");
  return (
    <div className="flex flex-col border border-border2 bg-paper">
      <div className="flex items-baseline justify-between border-b border-border px-3.5 py-2">
        <Caps className={hasErr ? "text-accent" : ""}>CFN HTTP</Caps>
        <span className="font-mono text-micro text-faint">{fmtNum(cfn?.calls)}</span>
      </div>
      <div className="flex-1 px-3.5 py-2">
        <Row k="mgmt" v={fmtNum(cfn?.["calls.mgmt"])} />
        <Row k="node" v={fmtNum(cfn?.["calls.node"])} />
        <div className="my-1.5 h-px bg-border" />
        {codes.length === 0 ? (
          <div className="py-0.5 text-micro italic text-faint">no calls</div>
        ) : codes.map(({ code, count }) => {
          const k = statusKind(code);
          const label = code === "0" ? "transport err" : `HTTP ${code}`;
          return (
            <Row
              key={code}
              k={label}
              v={fmtNum(count)}
              alert={k !== "ok"}
            />
          );
        })}
      </div>
    </div>
  );
}

function Row({ k, v, alert = false, dim = false }: {
  k: string; v: ReactNode; alert?: boolean; dim?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <span className={`text-micro lowercase ${alert ? "text-accent" : "text-muted-foreground"}`}>{k}</span>
      <span className={`font-mono text-label font-semibold tabular ${
        alert ? "italic text-accent" : dim ? "text-faint" : "text-text"
      }`}>
        {v}
      </span>
    </div>
  );
}

// ── Agent activity table (collector) ──────────────────────────────────────

const AGENT_COLS = "1.4fr 0.9fr 0.9fr 0.7fr 1.2fr 0.6fr";

function AgentActivityTable({ collector }: { collector: CollectorMetrics }) {
  const agents = deriveAgents(collector);
  const total = Math.max(0.0001, agents.reduce((s, a) => s + a.tokens, 0));
  return (
    <div className="border-b border-border2 px-6 py-5">
      <div className="mb-3.5 flex items-baseline justify-between">
        <Caps className="text-muted-foreground">AGENT ACTIVITY</Caps>
        <span className="font-mono text-micro italic text-faint">
          collector · {(collector.sessions || []).length} sessions · {agents.length} agents
        </span>
      </div>
      {agents.length === 0 ? (
        <div className="border border-dashed border-border2 bg-paper px-5 py-4">
          <Caps>WAITING ON OTLP</Caps>
          <p className="mt-1.5 max-w-[640px] text-micro leading-relaxed text-muted-foreground">
            The collector is online but no OpenClaw agents are exporting traces. Wire it up with{" "}
            <span className="font-mono text-accent">mycelium adapter add openclaw --step=otel</span>{" "}
            and send a message through one of your configured channels. Per-agent rows appear here as soon as the first trace arrives.
          </p>
        </div>
      ) : (
        <div className="border border-border2 bg-paper">
          <div className="grid items-center gap-3.5 border-b border-border2 px-4 py-2"
               style={{ gridTemplateColumns: AGENT_COLS }}>
            <Caps>AGENT</Caps>
            <Caps>TOKENS</Caps>
            <Caps>COST</Caps>
            <Caps>SESSIONS</Caps>
            <Caps>TOKEN SHARE</Caps>
            <Caps className="text-right">LAST</Caps>
          </div>
          {agents.map((a, i) => (
            <div key={a.agent}
                 className={`grid items-center gap-3.5 px-4 py-2.5 ${
                   i < agents.length - 1 ? "border-b border-border" : ""
                 }`}
                 style={{ gridTemplateColumns: AGENT_COLS }}>
              <span className="text-label font-semibold text-text">{a.agent}</span>
              <span className="font-mono text-label tabular text-text">{fmtNum(a.tokens)}</span>
              <span className="font-mono text-label tabular text-text">{fmtUsd(a.cost)}</span>
              <span className="font-mono text-label tabular text-muted-foreground">{a.sessions}</span>
              <div className="flex items-center gap-2">
                <div className="relative h-1 w-[120px] flex-shrink-0 bg-border">
                  <div className="absolute inset-y-0 left-0 bg-accent/85"
                       style={{ width: `${(a.tokens / total) * 100}%` }} />
                </div>
                <span className="font-mono text-micro tabular text-muted-foreground">
                  {Math.round((a.tokens / total) * 100)}%
                </span>
              </div>
              <span className="font-mono text-micro text-muted-foreground text-right">{a.last}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── By-model table (collector) ────────────────────────────────────────────

const MODEL_COLS = "1.6fr 0.9fr 0.9fr 0.6fr 1.2fr 0.7fr";

function ByModelTable({ models }: { models: ByModel[] }) {
  const total = models.reduce((s, m) => s + m.cost_usd, 0) || 0.0001;
  if (models.length === 0) {
    return (
      <div className="border border-border2 bg-paper px-5 py-4 text-micro italic text-faint">
        no model usage yet
      </div>
    );
  }
  return (
    <div className="border border-border2 bg-paper">
      <div className="grid items-center gap-3.5 border-b border-border2 px-4 py-2"
           style={{ gridTemplateColumns: MODEL_COLS }}>
        <Caps>MODEL</Caps>
        <Caps>IN</Caps>
        <Caps>OUT</Caps>
        <Caps>CALLS</Caps>
        <Caps>SHARE OF SPEND</Caps>
        <Caps className="text-right">COST</Caps>
      </div>
      {models.map((m, i) => (
        <div key={m.model}
             className={`grid items-center gap-3.5 px-4 py-2.5 ${
               i < models.length - 1 ? "border-b border-border" : ""
             }`}
             style={{ gridTemplateColumns: MODEL_COLS }}>
          <span className="font-mono text-label font-semibold text-text">{m.model}</span>
          <span className="font-mono text-label tabular text-text">{fmtNum(m.tokens_in)}</span>
          <span className="font-mono text-label tabular text-text">{fmtNum(m.tokens_out)}</span>
          <span className="font-mono text-label tabular text-muted-foreground">{m.calls}</span>
          <div className="flex items-center gap-2">
            <div className="relative h-1 w-[120px] flex-shrink-0 bg-border">
              <div className="absolute inset-y-0 left-0 bg-accent"
                   style={{ width: `${(m.cost_usd / total) * 100}%` }} />
            </div>
            <span className="font-mono text-micro tabular text-muted-foreground">
              {Math.round((m.cost_usd / total) * 100)}%
            </span>
          </div>
          <span className="font-mono text-label font-semibold tabular text-text text-right">{fmtUsd(m.cost_usd)}</span>
        </div>
      ))}
    </div>
  );
}

// ── Plates ────────────────────────────────────────────────────────────────

function CollectorOffPlate() {
  return (
    <div className="relative grid items-center gap-8 overflow-hidden border border-dashed border-border2 bg-paper px-7 py-8"
         style={{ gridTemplateColumns: "1fr auto" }}>
      {/* folded corner */}
      <div className="absolute top-0 right-0"
           style={{
             width: 0, height: 0,
             borderTop: "28px solid var(--surface)",
             borderLeft: "28px solid transparent",
           }} />
      <div>
        <Caps>DISABLED MODE</Caps>
        <div className="mt-1.5 text-ui font-semibold leading-snug text-text">
          Cost, agent activity, and per-model breakdowns are{" "}
          <span className="text-accent">not collected</span> on this host.
        </div>
        <div className="mt-2 max-w-[620px] text-micro leading-relaxed text-muted-foreground">
          The backend dashboard above is fully populated; the collector adds OpenClaw OTLP traces
          and a Prometheus scrape of CFN. Start it in another terminal and this section will
          populate within 30 seconds.
        </div>
      </div>
      <div className="flex flex-col items-end gap-2">
        <Caps>Run</Caps>
        <div className="rounded-lg border border-border bg-surface px-3.5 py-2.5 font-mono text-label font-semibold text-accent">
          mycelium metrics collect
        </div>
        <span className="font-mono text-micro text-faint">polls every 30s</span>
      </div>
    </div>
  );
}

function BackendDownPlate() {
  return (
    <div className="flex flex-1 items-center justify-center p-10">
      <div className="relative max-w-[560px] overflow-hidden rounded-xl border border-border bg-paper px-9 py-8">
        <div className="absolute inset-y-0 left-0 w-[3px] bg-yellow" />
        <Caps className="text-yellow">Backend unreachable</Caps>
        <div className="mt-1.5 text-ui font-semibold leading-snug text-text">
          Could not reach <span className="font-mono text-accent">GET /api/observability</span>
        </div>
        <div className="mt-2.5 text-micro leading-relaxed text-muted-foreground">
          The frontend is running but the backend isn&apos;t responding. Start it with{" "}
          <span className="font-mono text-accent">mycelium up</span> or check that postgres is
          reachable on the configured port.
        </div>
      </div>
    </div>
  );
}

// ── Spoke Sites ───────────────────────────────────────────────────────────

function SpokeSitesTable({
  hosts, activeHost, onHostClick,
}: {
  hosts: HostInfo[];
  activeHost: string | null;
  onHostClick: (host: string | null) => void;
}) {
  if (hosts.length === 0) return null;
  return (
    <div className="border-b border-border2 px-6 py-5">
      <div className="mb-3.5 flex items-baseline justify-between">
        <Caps className="text-muted-foreground">SPOKE SITES</Caps>
        <span className="font-mono text-micro italic text-faint">hosts reporting OTLP data</span>
      </div>
      {activeHost && (
        <div className="mb-3 flex items-center gap-2">
          <span className="text-micro text-muted-foreground">Filtered to</span>
          <span className="rounded-full border border-accent/30 bg-accent-soft px-2 py-0.5 font-mono text-micro font-semibold text-accent">
            {activeHost}
          </span>
          <button
            onClick={() => onHostClick(null)}
            className="text-micro text-faint hover:text-text transition-colors"
          >
            clear
          </button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-micro">
          <thead>
            <tr className="border-b border-border text-left text-faint">
              <th className="py-1.5 pr-4 font-normal">HOST</th>
              <th className="py-1.5 pr-4 font-normal">AGENTS</th>
              <th className="py-1.5 pr-4 font-normal text-right">SPANS</th>
              <th className="py-1.5 pr-4 font-normal text-right">TRACES</th>
              <th className="py-1.5 pr-4 font-normal text-right">ERRORS</th>
              <th className="py-1.5 font-normal">LAST SEEN</th>
            </tr>
          </thead>
          <tbody>
            {hosts.map(h => {
              const isActive = activeHost === h.host;
              return (
                <tr
                  key={h.host}
                  onClick={() => onHostClick(isActive ? null : h.host)}
                  className={`border-b border-border/50 cursor-pointer transition-colors ${
                    isActive ? "bg-accent-soft" : "hover:bg-hairline"
                  }`}
                >
                  <td className="py-1.5 pr-4 font-semibold text-text">{h.host}</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">{h.agents.join(", ") || "-"}</td>
                  <td className="py-1.5 pr-4 text-right tabular text-muted-foreground">{h.span_count.toLocaleString()}</td>
                  <td className="py-1.5 pr-4 text-right tabular text-muted-foreground">{h.trace_count.toLocaleString()}</td>
                  <td className={`py-1.5 pr-4 text-right tabular ${h.error_count > 0 ? "text-red-400 font-semibold" : "text-faint"}`}>
                    {h.error_count}
                  </td>
                  <td className="py-1.5 text-faint">{fmtAgo(h.last_seen)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────

export function MetricsScreen() {
  const [backend, setBackend] = useState<BackendMetrics | null>(null);
  const [collector, setCollector] = useState<CollectorMetrics | null>(null);
  const [hosts, setHosts] = useState<HostInfo[]>([]);
  const [hostFilter, setHostFilter] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [intervalSec, setIntervalSec] = useState(10);
  const [backendUnreachable, setBackendUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const b = await fetchBackendMetrics<BackendMetrics>();
      if (cancelled) return;
      setBackend(b);
      setBackendUnreachable(b == null);
      const c = await fetchCollectorMetrics<CollectorMetrics>();
      if (cancelled) return;
      setCollector(c);
      const h = await fetchHosts();
      if (cancelled) return;
      setHosts(h?.hosts ?? []);
    };
    load();
    if (paused) return () => { cancelled = true; };
    const id = window.setInterval(load, intervalSec * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [paused, intervalSec]);

  // Backend-down branch
  if (backendUnreachable && !backend) {
    return (
      <div className="flex flex-1 flex-col">
        <HeaderBand
          backend={null} collectorOn={false}
          paused={paused} setPaused={setPaused}
          intervalSec={intervalSec} setIntervalSec={setIntervalSec}
        />
        <BackendDownPlate />
      </div>
    );
  }

  const bc = backend?.counters || {};
  const bh = backend?.histograms || {};
  const cc = collector?.counters || {};
  const collectorOn = !!collector;

  // KPIs
  const tokensTotal = cc.tokens?.total?.total;
  const spendValue = collectorOn ? fmtUsd(cc.cost_usd?.total) : "-";

  const errStats = errorRate(bc.cfn);
  const errIsZero = errStats.total === 0;
  const errPct = errStats.total > 0 ? errStats.rate * 100 : 0;
  const errValue = errIsZero ? "-" : (errPct < 1 ? errPct.toFixed(2) + "%" : errPct.toFixed(1) + "%");
  const errAlert = errPct > 1;

  const llmCalls = (bc.llm?.calls || 0) + (bc.cfn?.calls || 0);
  const throughputValue = collectorOn
    ? `${fmtNum(cc.messages?.processed)} msg`
    : `${fmtNum(llmCalls)} calls`;

  // zero-data: backend up but nothing has happened yet
  const zeroData =
    (bc.embeddings?.computed || 0) === 0 &&
    (bc.memory?.writes || 0) === 0 &&
    (bc.coordination?.sessions_started || 0) === 0;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <HeaderBand
        backend={backend} collectorOn={collectorOn}
        paused={paused} setPaused={setPaused}
        intervalSec={intervalSec} setIntervalSec={setIntervalSec}
      />

      <div className="flex-1 overflow-y-auto">
        {/* ── KPI band ─────────────────────────────────────────────────── */}
        <div className="grid border-b border-border2"
             style={{ gridTemplateColumns: "1.1fr 1fr 1fr" }}>
          <KpiPlate
            label="SPEND"
            value={spendValue}
            sub={collectorOn ? (
              <>
                <span className="text-muted-foreground">{Object.keys(collector?.counters?.tokens?.by_model || {}).length}</span>{" "}
                models <span className="mx-1 text-faint">·</span>{" "}
                <span className="text-muted-foreground">{fmtNum(tokensTotal)}</span> tokens
                <span className="mx-1 text-faint">·</span>{" "}
                since <span className="text-muted-foreground">{fmtDur(backend?.started_at)}</span>
              </>
            ) : "requires collector"}
            sparkline={collector?.spend_5m}
            disabled={!collectorOn}
            cta={!collectorOn ? "mycelium metrics collect" : undefined}
          />
          <KpiPlate
            label="ERROR RATE"
            value={errValue}
            alert={errAlert}
            errorRatePct={errPct}
            sub={errIsZero ? "no CFN calls yet" : (
              <>
                <span className={errAlert ? "italic text-accent" : "text-muted-foreground"}>{errStats.errors}</span>
                {" of "}
                <span className="text-muted-foreground">{errStats.total}</span> CFN calls failed
              </>
            )}
            sparkline={collector?.err_5m}
          />
          <KpiPlate
            label="ACTIVITY"
            value={throughputValue}
            sub={collectorOn ? (
              <>
                <span className="text-muted-foreground">{cc.messages?.queued ?? 0}</span> queued
                <span className="mx-1 text-faint">·</span>
                <span className="text-muted-foreground">{cc.sessions_stuck ?? 0}</span> stuck
                <span className="mx-1 text-faint">·</span>{" "}
                since <span className="text-muted-foreground">{fmtDur(backend?.started_at)}</span>
              </>
            ) : (
              <>
                <span className="text-muted-foreground">{bc.coordination?.sessions_started ?? 0}</span>{" "}
                sessions <span className="mx-1 text-faint">·</span>{" "}
                <span className="text-muted-foreground">{bc.coordination?.rounds ?? 0}</span> rounds
                <span className="mx-1 text-faint">·</span>{" "}
                since <span className="text-muted-foreground">{fmtDur(backend?.started_at)}</span>
              </>
            )}
          />
        </div>

        {/* ── Zero-data nudge / agent activity ─────────────────────────── */}
        {zeroData ? (
          <div className="border-b border-border2 px-7 py-8">
            <Caps>NO TRAFFIC YET</Caps>
            <div className="mt-1.5 max-w-[720px] text-ui leading-relaxed text-muted-foreground">
              The system is up and the backend is reporting in, but no agents have written memory,
              run a search, or started a session yet. Numbers below will fill in as soon as
              anything moves.
            </div>
          </div>
        ) : collectorOn && collector ? (
          <AgentActivityTable collector={collector} />
        ) : (
          <div className="border-b border-border2 px-6 py-5">
            <CollectorOffPlate />
          </div>
        )}

        {/* ── Spoke sites ──────────────────────────────────────────────── */}
        {hosts.length > 0 && (
          <SpokeSitesTable hosts={hosts} activeHost={hostFilter} onHostClick={setHostFilter} />
        )}

        {/* ── Diagnostic grid ──────────────────────────────────────────── */}
        <div className="px-6 py-5">
          <div className="mb-3.5 flex items-baseline justify-between">
            <Caps className="text-muted-foreground">DIAGNOSTICS · BACKEND COUNTERS</Caps>
            <span className="font-mono text-micro italic text-faint">always available · GET /api/observability</span>
          </div>

          <div className="mb-4 grid border border-border2 bg-paper" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <LatencyStrip name="EMBEDDINGS · LATENCY" h={bh["embeddings.latency_ms"]} />
            <LatencyStrip name="CFN · LATENCY" h={bh["cfn.latency_ms"]} />
            <LatencyStrip name="MEMORY SEARCH · LATENCY" h={bh["memory.search_latency_ms"]} />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            <DiagTile
              title="MEMORY & SEARCH"
              rows={[
                ["writes",     fmtNum(bc.memory?.writes)],
                ["embedded",   fmtNum(bc.memory?.writes_embedded)],
                ["searches",   fmtNum(bc.memory?.searches)],
                ["hits",       fmtNum(bc.memory?.search_hits)],
                ["hit rate",
                  (bc.memory?.searches || 0) > 0
                    ? Math.round(100 * (bc.memory?.search_hits || 0) / (bc.memory!.searches!)) + "%"
                    : "-",
                  { dim: !(bc.memory?.searches) }],
                ["embeddings", fmtNum(bc.embeddings?.computed)],
              ]}
              footer={`saved ${fmtUsd(bc.embeddings?.["estimated_cost_avoided_usd"])} via local model`}
            />
            <DiagTile
              title="COORDINATION"
              alert={(bc.coordination?.["outcome.failure"] || 0) > 0}
              rows={[
                ["sessions",   fmtNum(bc.coordination?.sessions_started)],
                ["rounds",     fmtNum(bc.coordination?.rounds)],
                ["consensus",  fmtNum(bc.coordination?.consensus_reached)],
                ["success",    fmtNum(bc.coordination?.["outcome.success"])],
                ["failure",    fmtNum(bc.coordination?.["outcome.failure"]),
                  {
                    alert: (bc.coordination?.["outcome.failure"] || 0) > 0,
                    dim: !(bc.coordination?.["outcome.failure"]),
                  }],
              ]}
            />
            <DiagTile
              title="INDEXER"
              alert={(bc.indexer?.errors || 0) > 0}
              rows={[
                ["runs",          fmtNum(bc.indexer?.runs)],
                ["files indexed", fmtNum(bc.indexer?.files_indexed)],
                ["files pruned",  fmtNum(bc.indexer?.files_pruned), { dim: !(bc.indexer?.files_pruned) }],
                ["errors",        fmtNum(bc.indexer?.errors),
                  { alert: (bc.indexer?.errors || 0) > 0, dim: !(bc.indexer?.errors) }],
              ]}
              footer={(bc.indexer?.errors || 0) > 0 ? "tail logs: mycelium logs --grep indexer" : undefined}
            />
            <DiagTile
              title="KNOWLEDGE GRAPH"
              rows={[
                ["ingestions", fmtNum(bc.knowledge?.ingestions)],
                ["concepts",   fmtNum(bc.knowledge?.concepts_extracted)],
                ["relations",  fmtNum(bc.knowledge?.relations_extracted)],
                ["synth runs", fmtNum(bc.synthesis?.runs)],
                ["briefings",  fmtNum(bc.synthesis?.briefings)],
              ]}
            />
            <CfnStatusTile cfn={bc.cfn} />
          </div>

          {/* Token / LLM strip: quiet, secondary */}
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <DiagTile
              title="MYCELIUM LLM (BACKEND)"
              rows={[
                ["calls",         fmtNum(bc.llm?.calls)],
                ["input tokens",  fmtNum(bc.llm?.input_tokens)],
                ["output tokens", fmtNum(bc.llm?.output_tokens)],
                ["cached",        fmtNum(bc.llm?.cached_tokens), { dim: !(bc.llm?.cached_tokens) }],
                ["cache rate",
                  (bc.llm?.input_tokens || 0) > 0
                    ? Math.round(100 * (bc.llm?.cached_tokens || 0) / ((bc.llm?.input_tokens || 0) + (bc.llm?.cached_tokens || 0))) + "%"
                    : "-",
                  { dim: !(bc.llm?.cached_tokens) }],
              ]}
            />
            <DiagTile
              title="CFN LLM"
              rows={[
                ["calls",         fmtNum(bc.cfn_llm?.calls)],
                ["input tokens",  fmtNum(bc.cfn_llm?.input_tokens)],
                ["output tokens", fmtNum(bc.cfn_llm?.output_tokens)],
                ["cached",        fmtNum(bc.cfn_llm?.cached_tokens), { dim: !(bc.cfn_llm?.cached_tokens) }],
              ]}
            />
          </div>
        </div>

        {/* ── By-model spend (collector only) ──────────────────────────── */}
        {collectorOn && collector && (() => {
          const models = deriveModels(collector);
          if (models.length === 0) return null;
          return (
            <div className="px-6 pb-6">
              <div className="my-3.5 flex items-baseline justify-between">
                <Caps className="text-muted-foreground">SPEND · BY MODEL</Caps>
                <span className="font-mono text-micro italic text-faint">OpenClaw OTLP</span>
              </div>
              <ByModelTable models={models} />
            </div>
          );
        })()}
      </div>
    </div>
  );
}
