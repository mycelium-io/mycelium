// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchBackendMetrics, fetchCollectorMetrics } from "@/lib/api";
import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";
import { MetricCard, StatRow, fmt, fmtUsd, fmtDuration } from "@/components/metric-card";

function get(obj: Record<string, unknown> | undefined, key: string): number {
  if (!obj) return 0;
  return (obj[key] as number) ?? 0;
}

const crumbs: Crumb[] = [{ label: "metrics", href: "/metrics" }, { label: "cards" }];

export default function MetricsCardsPage() {
  const [backend, setBackend] = useState<Record<string, unknown> | null>(null);
  const [collector, setCollector] = useState<Record<string, unknown> | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const load = () => {
      fetchBackendMetrics().then(setBackend).catch(() => setBackend(null));
      fetchCollectorMetrics().then(setCollector).catch(() => setCollector(null));
    };
    load();
    const t = setInterval(() => { load(); setTick(n => n + 1); }, 10_000);
    return () => clearInterval(t);
  }, []);

  const bc = backend?.counters as Record<string, Record<string, number>> | undefined;
  const bh = backend?.histograms as Record<string, Record<string, unknown>> | undefined;

  const cc = collector?.counters as Record<string, unknown> | undefined;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar
        activeTab="metrics"
        actions={
          <Link
            href="/metrics/tables"
            className="flex items-center gap-2 border border-border2 px-3 py-1.5 caps-mono-sm text-muted transition-colors hover:text-text hover:border-accent/40"
          >
            TABLE VIEW
          </Link>
        }
      />
      <SubNav crumbs={crumbs} />

      <main className="flex-1 overflow-y-auto p-6">
        {/* ── Backend Metrics (always available) ──────────────────────── */}
        <SectionHeader title="Backend Metrics" subtitle="always available" />

        {!backend ? (
          <div className="px-4 py-12 text-center italic text-muted">
            connecting to backend...
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 mb-8">
            <MetricCard title="System" accent="default">
              <StatRow label="uptime" value={fmtDuration(backend.started_at as string)} />
              <StatRow label="last update" value={relAgo(backend.updated_at as string)} />
            </MetricCard>

            <MetricCard title="Embeddings" accent="green">
              <StatRow label="computed" value={fmt(get(bc?.embeddings, "computed"))} />
              <StatRow label="est. tokens" value={fmt(get(bc?.embeddings, "estimated_tokens"))} />
              <StatRow label="source" value={bc?.embeddings?.["by_source.local"] ? "local" : "remote"} />
            </MetricCard>

            <MetricCard title="Memory" accent="green">
              <StatRow label="writes" value={fmt(get(bc?.memory, "writes"))} />
              <StatRow label="searches" value={fmt(get(bc?.memory, "searches"))} />
              <StatRow label="results returned" value={fmt(get(bc?.memory, "results_returned"))} />
            </MetricCard>

            <MetricCard title="Indexer" accent={get(bc?.indexer, "errors") > 0 ? "red" : "green"}>
              <StatRow label="runs" value={fmt(get(bc?.indexer, "runs"))} />
              <StatRow label="files indexed" value={fmt(get(bc?.indexer, "files_indexed"))} />
              <StatRow label="files pruned" value={fmt(get(bc?.indexer, "files_pruned"))} />
              <StatRow
                label="errors"
                value={fmt(get(bc?.indexer, "errors"))}
                dim={get(bc?.indexer, "errors") === 0}
              />
            </MetricCard>

            <MetricCard title="Coordination" accent="default">
              <StatRow label="sessions started" value={fmt(get(bc?.coordination, "sessions_started"))} />
              <StatRow label="rounds" value={fmt(get(bc?.coordination, "rounds"))} />
              <StatRow label="consensus" value={fmt(get(bc?.coordination, "consensus_reached"))} />
              <StatRow label="success" value={fmt(get(bc?.coordination, "outcome.success"))} />
              <StatRow
                label="failure"
                value={fmt(get(bc?.coordination, "outcome.failure"))}
                dim={get(bc?.coordination, "outcome.failure") === 0}
              />
            </MetricCard>

            <MetricCard title="Mycelium LLM" accent="default">
              <StatRow label="calls" value={fmt(get(bc?.llm, "calls"))} />
              <StatRow label="input tokens" value={fmt(get(bc?.llm, "input_tokens"))} />
              <StatRow label="output tokens" value={fmt(get(bc?.llm, "output_tokens"))} />
              <StatRow label="cached tokens" value={fmt(get(bc?.llm, "cached_tokens"))} dim={get(bc?.llm, "cached_tokens") === 0} />
            </MetricCard>

            <MetricCard title="CFN Calls" accent={hasCfnErrors(bc?.cfn) ? "yellow" : "default"}>
              <StatRow label="total" value={fmt(get(bc?.cfn, "calls"))} />
              <StatRow label="mgmt" value={fmt(get(bc?.cfn, "calls.mgmt"))} />
              <StatRow label="node" value={fmt(get(bc?.cfn, "calls.node"))} />
              {renderStatusCodes(bc?.cfn)}
            </MetricCard>

            <MetricCard title="CFN LLM" accent="default">
              <StatRow label="calls" value={fmt(get(bc?.cfn_llm, "calls"))} />
              <StatRow label="input tokens" value={fmt(get(bc?.cfn_llm, "input_tokens"))} />
              <StatRow label="output tokens" value={fmt(get(bc?.cfn_llm, "output_tokens"))} />
              <StatRow label="cached tokens" value={fmt(get(bc?.cfn_llm, "cached_tokens"))} dim={get(bc?.cfn_llm, "cached_tokens") === 0} />
            </MetricCard>

            <MetricCard title="Synthesis" accent="default">
              <StatRow label="runs" value={fmt(get(bc?.synthesis, "runs"))} />
              <StatRow label="briefings" value={fmt(get(bc?.synthesis, "briefings"))} />
              <StatRow label="cache hits" value={fmt(get(bc?.synthesis, "cache_hits"))} />
              <StatRow label="cache misses" value={fmt(get(bc?.synthesis, "cache_misses"))} />
            </MetricCard>

            <MetricCard title="Knowledge" accent="default">
              <StatRow label="ingestions" value={fmt(get(bc?.knowledge, "ingestions"))} />
              <StatRow label="concepts" value={fmt(get(bc?.knowledge, "concepts_extracted"))} />
              <StatRow label="relations" value={fmt(get(bc?.knowledge, "relations_extracted"))} />
            </MetricCard>
          </div>
        )}

        {/* ── Collector Metrics (requires mycelium metrics collect) ────── */}
        <SectionHeader
          title="Collector Metrics"
          subtitle={collector ? "from mycelium metrics collect" : "requires: mycelium metrics collect"}
        />

        {!collector ? (
          <CollectorOfflineBanner />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 mb-8">
            <MetricCard title="OpenClaw Tokens" accent="green">
              <StatRow label="input" value={fmt((cc?.tokens as Record<string, unknown>)?.total as Record<string, number> && ((cc?.tokens as Record<string, Record<string, number>>)?.total?.input))} />
              <StatRow label="output" value={fmt(((cc?.tokens as Record<string, Record<string, number>>)?.total?.output))} />
              <StatRow label="cache read" value={fmt(((cc?.tokens as Record<string, Record<string, number>>)?.total?.cache_read))} />
              <StatRow label="total" value={fmt(((cc?.tokens as Record<string, Record<string, number>>)?.total?.total))} />
            </MetricCard>

            <MetricCard title="OpenClaw Cost" accent="green">
              <StatRow label="total" value={fmtUsd((cc?.cost_usd as Record<string, number>)?.total)} />
            </MetricCard>

            <MetricCard title="Messages" accent="default">
              <StatRow label="processed" value={fmt((cc?.messages as Record<string, number>)?.processed)} />
              <StatRow label="queued" value={fmt((cc?.messages as Record<string, number>)?.queued)} />
            </MetricCard>

            <MetricCard title="Sessions" accent="default">
              <StatRow label="total" value={fmt((collector?.sessions as unknown[])?.length)} />
              <StatRow label="stuck" value={fmt(cc?.sessions_stuck as number)} dim={(cc?.sessions_stuck as number) === 0} />
            </MetricCard>

            {renderScrapeCards(collector?.scrape as Record<string, Record<string, unknown>> | undefined)}
          </div>
        )}
      </main>

      <Footer updatedAt={backend?.updated_at as string} tick={tick} />
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-4 mt-2">
      <h2 className="caps-mono text-text">{title}</h2>
      <span className="text-micro text-dim italic">{subtitle}</span>
    </div>
  );
}

function CollectorOfflineBanner() {
  return (
    <div className="border border-border bg-surface/60 px-6 py-8 mb-8 text-center">
      <p className="text-muted mb-1">Collector is not running</p>
      <p className="text-micro text-dim">
        Start with: <code className="text-accent">mycelium metrics collect</code>
      </p>
    </div>
  );
}

function Footer({ updatedAt, tick }: { updatedAt?: string; tick: number }) {
  return (
    <div className="flex flex-shrink-0 items-center gap-6 border-t border-border2 bg-paper px-6 py-2.5">
      <span className="text-micro text-muted">
        last update: <span className="text-text tabular">{updatedAt ? relAgo(updatedAt) : "—"}</span>
      </span>
      <span className="text-micro text-dim">auto-refresh 10s</span>
      <span className="text-micro text-dim tabular">tick #{tick}</span>
    </div>
  );
}

function relAgo(iso: string | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const sec = Math.floor((Date.now() - t) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ${min % 60}m ago`;
}

function hasCfnErrors(cfn: Record<string, number> | undefined): boolean {
  if (!cfn) return false;
  return Object.keys(cfn).some(k => k.startsWith("status.") && parseInt(k.split(".")[1]) >= 400);
}

function renderStatusCodes(cfn: Record<string, number> | undefined) {
  if (!cfn) return null;
  const codes = Object.entries(cfn)
    .filter(([k]) => k.startsWith("status."))
    .map(([k, v]) => ({ code: k.replace("status.", ""), count: v }))
    .sort((a, b) => a.code.localeCompare(b.code));
  if (codes.length === 0) return null;
  return (
    <div className="mt-2 pt-2 border-t border-border">
      {codes.map(({ code, count }) => (
        <StatRow
          key={code}
          label={code === "0" ? "transport err" : `HTTP ${code}`}
          value={fmt(count)}
          dim={count === 0}
        />
      ))}
    </div>
  );
}

function renderScrapeCards(scrape: Record<string, Record<string, unknown>> | undefined) {
  if (!scrape) return null;
  return Object.entries(scrape).map(([name, entry]) => {
    const data = entry?.data as Record<string, number> | undefined;
    if (!data) return null;
    const rows = Object.entries(data).slice(0, 12);
    return (
      <MetricCard key={name} title={`CFN Scrape: ${name}`} accent="default">
        {rows.map(([k, v]) => (
          <StatRow key={k} label={k} value={typeof v === "number" ? fmt(v) : String(v)} />
        ))}
      </MetricCard>
    );
  });
}
