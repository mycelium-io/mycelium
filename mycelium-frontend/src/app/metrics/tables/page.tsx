// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchBackendMetrics, fetchCollectorMetrics } from "@/lib/api";
import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";
import { fmt, fmtUsd, fmtDuration } from "@/components/metric-card";

function get(obj: Record<string, unknown> | undefined, key: string): number {
  if (!obj) return 0;
  return (obj[key] as number) ?? 0;
}

const crumbs: Crumb[] = [{ label: "metrics", href: "/metrics" }, { label: "tables" }];

export default function MetricsTablesPage() {
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
  const cc = collector?.counters as Record<string, unknown> | undefined;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar
        activeTab="metrics"
        actions={
          <Link
            href="/metrics/cards"
            className="flex items-center gap-2 border border-border2 px-3 py-1.5 caps-mono-sm text-muted transition-colors hover:text-text hover:border-accent/40"
          >
            CARD VIEW
          </Link>
        }
      />
      <SubNav crumbs={crumbs} />

      <main className="flex-1 overflow-y-auto p-6 font-mono" style={{ fontFamily: "var(--font-mono)" }}>
        {/* ── Backend Metrics ──────────────────────────────────────── */}
        <SectionTitle title="Backend Metrics" note="always available" />

        {!backend ? (
          <p className="text-muted italic py-8 text-center">connecting to backend...</p>
        ) : (
          <div className="space-y-6 mb-10">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Left column */}
              <div className="space-y-6">
                <Table title="System">
                  <Row label="uptime" value={fmtDuration(backend.started_at as string)} />
                  <Row label="last update" value={relAgo(backend.updated_at as string)} />
                </Table>

                <Table title="Embeddings">
                  <Row label="computed" value={fmt(get(bc?.embeddings, "computed"))} />
                  <Row label="est. tokens" value={fmt(get(bc?.embeddings, "estimated_tokens"))} />
                  <Row label="source" value={bc?.embeddings?.["by_source.local"] ? "local" : "remote"} />
                </Table>

                <Table title="Memory">
                  <Row label="writes" value={fmt(get(bc?.memory, "writes"))} />
                  <Row label="searches" value={fmt(get(bc?.memory, "searches"))} />
                  <Row label="search hits" value={fmt(get(bc?.memory, "search_hits"))} />
                  <Row label="results" value={fmt(get(bc?.memory, "results_returned"))} />
                </Table>

                <Table title="Indexer">
                  <Row label="runs" value={fmt(get(bc?.indexer, "runs"))} />
                  <Row label="indexed" value={fmt(get(bc?.indexer, "files_indexed"))} />
                  <Row label="pruned" value={fmt(get(bc?.indexer, "files_pruned"))} />
                  <Row label="errors" value={fmt(get(bc?.indexer, "errors"))} warn={get(bc?.indexer, "errors") > 0} />
                </Table>

                <Table title="Knowledge">
                  <Row label="ingestions" value={fmt(get(bc?.knowledge, "ingestions"))} />
                  <Row label="concepts" value={fmt(get(bc?.knowledge, "concepts_extracted"))} />
                  <Row label="relations" value={fmt(get(bc?.knowledge, "relations_extracted"))} />
                </Table>
              </div>

              {/* Right column */}
              <div className="space-y-6">
                <Table title="Coordination">
                  <Row label="sessions" value={fmt(get(bc?.coordination, "sessions_started"))} />
                  <Row label="rounds" value={fmt(get(bc?.coordination, "rounds"))} />
                  <Row label="consensus" value={fmt(get(bc?.coordination, "consensus_reached"))} />
                  <Row label="success" value={fmt(get(bc?.coordination, "outcome.success"))} />
                  <Row label="failure" value={fmt(get(bc?.coordination, "outcome.failure"))} warn={get(bc?.coordination, "outcome.failure") > 0} />
                </Table>

                <Table title="Mycelium LLM">
                  <Row label="calls" value={fmt(get(bc?.llm, "calls"))} />
                  <Row label="input tokens" value={fmt(get(bc?.llm, "input_tokens"))} />
                  <Row label="output tokens" value={fmt(get(bc?.llm, "output_tokens"))} />
                  <Row label="cached" value={fmt(get(bc?.llm, "cached_tokens"))} dim={get(bc?.llm, "cached_tokens") === 0} />
                </Table>

                <Table title="CFN Calls">
                  <Row label="total" value={fmt(get(bc?.cfn, "calls"))} />
                  <Row label="mgmt" value={fmt(get(bc?.cfn, "calls.mgmt"))} />
                  <Row label="node" value={fmt(get(bc?.cfn, "calls.node"))} />
                  <StatusCodeRows cfn={bc?.cfn} />
                </Table>

                <Table title="CFN LLM">
                  <Row label="calls" value={fmt(get(bc?.cfn_llm, "calls"))} />
                  <Row label="input tokens" value={fmt(get(bc?.cfn_llm, "input_tokens"))} />
                  <Row label="output tokens" value={fmt(get(bc?.cfn_llm, "output_tokens"))} />
                  <Row label="cached" value={fmt(get(bc?.cfn_llm, "cached_tokens"))} dim={get(bc?.cfn_llm, "cached_tokens") === 0} />
                </Table>

                <Table title="Synthesis">
                  <Row label="runs" value={fmt(get(bc?.synthesis, "runs"))} />
                  <Row label="briefings" value={fmt(get(bc?.synthesis, "briefings"))} />
                  <Row label="cache hits" value={fmt(get(bc?.synthesis, "cache_hits"))} />
                  <Row label="cache misses" value={fmt(get(bc?.synthesis, "cache_misses"))} />
                  <Row label="skipped" value={fmt(get(bc?.synthesis, "skipped"))} dim={get(bc?.synthesis, "skipped") === 0} />
                </Table>
              </div>
            </div>
          </div>
        )}

        {/* ── Collector Metrics ────────────────────────────────────── */}
        <SectionTitle
          title="Collector Metrics"
          note={collector ? "from mycelium metrics collect" : "requires: mycelium metrics collect"}
        />

        {!collector ? (
          <div className="border border-border bg-surface/60 px-6 py-8 mb-8 text-center">
            <p className="text-muted mb-1">Collector is not running</p>
            <p className="text-micro text-dim">
              Start with: <code className="text-accent">mycelium metrics collect</code>
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-10">
            <div className="space-y-6">
              <Table title="OpenClaw Tokens">
                {renderTokenRows(cc?.tokens as Record<string, Record<string, number>> | undefined)}
              </Table>

              <Table title="OpenClaw Cost">
                <Row label="total" value={fmtUsd((cc?.cost_usd as Record<string, number>)?.total)} />
              </Table>
            </div>

            <div className="space-y-6">
              <Table title="Messages">
                <Row label="processed" value={fmt((cc?.messages as Record<string, number>)?.processed)} />
                <Row label="queued" value={fmt((cc?.messages as Record<string, number>)?.queued)} />
              </Table>

              <Table title="Sessions">
                <Row label="total" value={fmt((collector?.sessions as unknown[])?.length)} />
                <Row label="stuck" value={fmt(cc?.sessions_stuck as number)} warn={(cc?.sessions_stuck as number) > 0} />
              </Table>

              {renderScrapeTable(collector?.scrape as Record<string, Record<string, unknown>> | undefined)}
            </div>
          </div>
        )}
      </main>

      <footer className="flex flex-shrink-0 items-center gap-6 border-t border-border2 bg-paper px-6 py-2.5">
        <span className="text-micro text-muted">
          last update: <span className="text-text tabular">{backend?.updated_at ? relAgo(backend.updated_at as string) : "—"}</span>
        </span>
        <span className="text-micro text-dim">auto-refresh 10s</span>
        <span className="text-micro text-dim tabular">tick #{tick}</span>
      </footer>
    </div>
  );
}

// ─── Table primitives ─────────────────────────────────────────────────────────

function SectionTitle({ title, note }: { title: string; note: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-4 mt-2">
      <h2 className="caps-mono text-text">{title}</h2>
      <span className="text-micro text-dim italic">{note}</span>
    </div>
  );
}

function Table({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border bg-paper">
      <div className="border-b border-border px-4 py-2 bg-surface/40">
        <span className="caps-mono-sm text-muted">{title}</span>
      </div>
      <div className="divide-y divide-border">{children}</div>
    </div>
  );
}

function Row({
  label,
  value,
  dim,
  warn,
}: {
  label: string;
  value: React.ReactNode;
  dim?: boolean;
  warn?: boolean;
}) {
  const valueColor = warn ? "text-[#f87171]" : dim ? "text-dim" : "text-text";
  return (
    <div className="flex items-center justify-between px-4 py-1.5">
      <span className="text-micro text-muted">{label}</span>
      <span className={`text-micro tabular font-semibold ${valueColor}`}>{value}</span>
    </div>
  );
}

// ─── Data helpers ─────────────────────────────────────────────────────────────

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

function StatusCodeRows({ cfn }: { cfn: Record<string, number> | undefined }) {
  if (!cfn) return null;
  const codes = Object.entries(cfn)
    .filter(([k]) => k.startsWith("status."))
    .map(([k, v]) => ({ code: k.replace("status.", ""), count: v }))
    .sort((a, b) => a.code.localeCompare(b.code));
  if (codes.length === 0) return null;
  return (
    <>
      {codes.map(({ code, count }) => (
        <Row
          key={code}
          label={code === "0" ? "transport err" : `HTTP ${code}`}
          value={fmt(count)}
          warn={parseInt(code) >= 400 || code === "0"}
          dim={count === 0}
        />
      ))}
    </>
  );
}

function renderTokenRows(tokens: Record<string, Record<string, number>> | undefined) {
  if (!tokens?.total) return <Row label="—" value="no data" dim />;
  const t = tokens.total;
  return (
    <>
      <Row label="input" value={fmt(t.input)} />
      <Row label="output" value={fmt(t.output)} />
      <Row label="cache read" value={fmt(t.cache_read)} dim={t.cache_read === 0} />
      <Row label="cache write" value={fmt(t.cache_write)} dim={t.cache_write === 0} />
      <Row label="total" value={fmt(t.total)} />
    </>
  );
}

function renderScrapeTable(scrape: Record<string, Record<string, unknown>> | undefined) {
  if (!scrape) return null;
  return Object.entries(scrape).map(([name, entry]) => {
    const data = entry?.data as Record<string, number> | undefined;
    if (!data) return null;
    return (
      <Table key={name} title={`CFN Scrape: ${name}`}>
        {Object.entries(data).slice(0, 12).map(([k, v]) => (
          <Row key={k} label={k} value={typeof v === "number" ? fmt(v) : String(v)} />
        ))}
      </Table>
    );
  });
}
