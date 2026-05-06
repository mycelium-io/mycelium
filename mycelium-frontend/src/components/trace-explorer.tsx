// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useState } from "react";
import type { TraceSummary, TraceSpan } from "@/lib/api";

interface TraceExplorerProps {
  traces: TraceSummary[] | null;
}

export function TraceExplorer({ traces }: TraceExplorerProps) {
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  if (traces === null) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p className="mb-2">No trace data available</p>
        <p className="text-micro text-dim">
          Start the collector: <code className="text-accent">mycelium metrics collect</code>
        </p>
      </div>
    );
  }

  if (traces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted">
        <p className="mb-2">No traces captured yet</p>
        <p className="text-micro text-dim">Traces will appear as agents process requests</p>
      </div>
    );
  }

  const filtered = filter
    ? traces.filter(t =>
        t.root_span.toLowerCase().includes(filter.toLowerCase()) ||
        t.agent.toLowerCase().includes(filter.toLowerCase()) ||
        t.service.toLowerCase().includes(filter.toLowerCase()) ||
        t.trace_id.includes(filter)
      )
    : traces;

  return (
    <div className="flex flex-col h-full">
      {/* Filter bar */}
      <div className="flex items-center gap-3 border-b border-border bg-paper px-5 py-2">
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter by span name, agent, service, or trace ID..."
          className="flex-1 bg-transparent text-micro text-text placeholder:text-dim outline-none"
        />
        <span className="text-micro text-dim tabular">{filtered.length} traces</span>
      </div>

      {/* Trace list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map(trace => (
          <div key={trace.trace_id} className="border-b border-border">
            {/* Trace summary row */}
            <button
              onClick={() => setExpandedTrace(expandedTrace === trace.trace_id ? null : trace.trace_id)}
              className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-surface/40 transition-colors"
            >
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${trace.has_error ? "bg-red-400" : "bg-green-500"}`} />

              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-micro font-semibold text-text truncate">{trace.root_span}</span>
                  {trace.agent && (
                    <span className="text-micro text-accent truncate">{trace.agent}</span>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="text-micro text-dim">{trace.service}</span>
                  <span className="text-micro text-dim">{trace.trace_id.slice(0, 16)}...</span>
                </div>
              </div>

              <div className="flex items-center gap-4 flex-shrink-0">
                <span className="text-micro text-muted tabular">{trace.span_count} spans</span>
                <span className="text-micro text-text tabular font-semibold">{fmtDuration(trace.duration_ms)}</span>
                <span className="text-micro text-dim tabular">{fmtTime(trace.start_time)}</span>
                <span className={`text-micro transition-transform ${expandedTrace === trace.trace_id ? "rotate-90" : ""}`}>
                  {"\u25B6"}
                </span>
              </div>
            </button>

            {/* Expanded waterfall */}
            {expandedTrace === trace.trace_id && (
              <TraceWaterfall spans={trace.spans} totalDuration={trace.duration_ms} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


function TraceWaterfall({ spans, totalDuration }: { spans: TraceSpan[]; totalDuration: number }) {
  const [selectedSpan, setSelectedSpan] = useState<TraceSpan | null>(null);

  if (!spans.length) return null;

  const tree = buildSpanTree(spans);
  const minStart = Math.min(...spans.map(s => new Date(s.start_time).getTime()));

  return (
    <div className="border-t border-border bg-bg">
      <div className="flex">
        {/* Waterfall */}
        <div className="flex-1 overflow-x-auto">
          {/* Time ruler */}
          <div className="flex items-center h-6 border-b border-border px-4 bg-surface/20">
            <span className="w-[260px] flex-shrink-0" />
            <div className="flex-1 flex justify-between text-micro text-dim tabular">
              <span>0ms</span>
              <span>{fmtDuration(totalDuration / 4)}</span>
              <span>{fmtDuration(totalDuration / 2)}</span>
              <span>{fmtDuration((totalDuration * 3) / 4)}</span>
              <span>{fmtDuration(totalDuration)}</span>
            </div>
          </div>

          {/* Span rows */}
          {tree.map(node => (
            <SpanRow
              key={node.span.span_id}
              node={node}
              depth={0}
              minStart={minStart}
              totalDuration={totalDuration || 1}
              selected={selectedSpan?.span_id === node.span.span_id}
              onSelect={setSelectedSpan}
            />
          ))}
        </div>

        {/* Detail panel */}
        {selectedSpan && (
          <div className="w-[340px] border-l border-border bg-paper overflow-y-auto">
            <SpanDetail span={selectedSpan} onClose={() => setSelectedSpan(null)} />
          </div>
        )}
      </div>
    </div>
  );
}

interface SpanNode {
  span: TraceSpan;
  children: SpanNode[];
}

function buildSpanTree(spans: TraceSpan[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>();
  for (const s of spans) {
    nodes.set(s.span_id, { span: s, children: [] });
  }

  const roots: SpanNode[] = [];
  for (const s of spans) {
    const node = nodes.get(s.span_id)!;
    if (s.parent_span_id && nodes.has(s.parent_span_id)) {
      nodes.get(s.parent_span_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortChildren = (n: SpanNode) => {
    n.children.sort((a, b) => new Date(a.span.start_time).getTime() - new Date(b.span.start_time).getTime());
    n.children.forEach(sortChildren);
  };
  roots.sort((a, b) => new Date(a.span.start_time).getTime() - new Date(b.span.start_time).getTime());
  roots.forEach(sortChildren);

  return roots;
}

function SpanRow({
  node, depth, minStart, totalDuration, selected, onSelect,
}: {
  node: SpanNode;
  depth: number;
  minStart: number;
  totalDuration: number;
  selected: boolean;
  onSelect: (s: TraceSpan) => void;
}) {
  const s = node.span;
  const spanStart = new Date(s.start_time).getTime();
  const offset = spanStart - minStart;
  const leftPct = (offset / totalDuration) * 100;
  const widthPct = Math.max((s.duration_ms / totalDuration) * 100, 0.5);

  const kindColors: Record<string, string> = {
    server: "bg-blue-500",
    client: "bg-amber-500",
    internal: "bg-emerald-500",
    producer: "bg-purple-500",
    consumer: "bg-pink-500",
  };
  const barColor = s.status === "error" ? "bg-red-400" : (kindColors[s.kind] || "bg-gray-400");

  return (
    <>
      <button
        onClick={() => onSelect(s)}
        className={`flex items-center w-full h-7 hover:bg-surface/40 transition-colors ${selected ? "bg-surface/60" : ""}`}
      >
        {/* Label */}
        <div
          className="w-[260px] flex-shrink-0 flex items-center gap-1 px-2 overflow-hidden"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {node.children.length > 0 && (
            <span className="text-micro text-dim">{"\u25BC"}</span>
          )}
          <span className={`text-micro truncate ${s.status === "error" ? "text-red-400" : "text-text"}`}>
            {s.name}
          </span>
          <span className="text-micro text-dim ml-1 tabular flex-shrink-0">{fmtDuration(s.duration_ms)}</span>
        </div>

        {/* Bar */}
        <div className="flex-1 relative h-full">
          <div
            className={`absolute top-1.5 h-4 rounded-sm ${barColor} opacity-80`}
            style={{ left: `${leftPct}%`, width: `${widthPct}%`, minWidth: "2px" }}
          />
        </div>
      </button>

      {node.children.map(child => (
        <SpanRow
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          minStart={minStart}
          totalDuration={totalDuration}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </>
  );
}

function SpanDetail({ span, onClose }: { span: TraceSpan; onClose: () => void }) {
  const attrs = Object.entries(span.attributes || {});

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="caps-mono-sm text-muted">Span Detail</h3>
        <button onClick={onClose} className="text-micro text-dim hover:text-text">{"\u2715"}</button>
      </div>

      <div className="space-y-2 mb-4">
        <DetailRow label="Name" value={span.name} />
        <DetailRow label="Kind" value={span.kind} />
        <DetailRow label="Status" value={span.status} warn={span.status === "error"} />
        {span.status_message && <DetailRow label="Message" value={span.status_message} />}
        <DetailRow label="Duration" value={fmtDuration(span.duration_ms)} />
        <DetailRow label="Service" value={span.service} />
        <DetailRow label="Started" value={fmtTime(span.start_time)} />
        <DetailRow label="Span ID" value={span.span_id} mono />
        <DetailRow label="Parent" value={span.parent_span_id || "(root)"} mono />
      </div>

      {attrs.length > 0 && (
        <>
          <h4 className="caps-mono-sm text-muted mb-2">Attributes</h4>
          <div className="space-y-1">
            {attrs.map(([k, v]) => (
              <div key={k} className="flex gap-2 text-micro">
                <span className="text-muted truncate flex-shrink-0" style={{ maxWidth: "140px" }}>{k}</span>
                <span className="text-text truncate">{String(v)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function DetailRow({ label, value, mono, warn }: { label: string; value: string; mono?: boolean; warn?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-micro text-muted">{label}</span>
      <span className={`text-micro tabular ${warn ? "text-red-400" : "text-text"} ${mono ? "font-mono" : ""} truncate`} style={{ maxWidth: "200px" }}>
        {value}
      </span>
    </div>
  );
}

function fmtDuration(ms: number): string {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const min = Math.floor(ms / 60000);
  const sec = Math.floor((ms % 60000) / 1000);
  return `${min}m${sec}s`;
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}
