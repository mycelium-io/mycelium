// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { fetchEpisode, type EpisodeDetail as EpisodeDetailT, type L9Envelope } from "@/lib/api";

function outcomeColor(state: string | null): string {
  if (state === "converged" || state === "resolved") return "var(--green)";
  if (state === "rejected") return "var(--yellow)";
  return "var(--accent)";
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-micro uppercase tracking-wide text-faint">{label}</span>
      <span className="text-label text-text">{children}</span>
    </div>
  );
}

function Stat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-surface px-3 py-2" title={title}>
      <span className="text-micro uppercase tracking-wide text-faint">{label}</span>
      <span className="font-mono text-label tabular text-text">{value}</span>
    </div>
  );
}

/** One L9 envelope in the causal chain. */
function EnvelopeRow({ env }: { env: L9Envelope }) {
  const kind = env.header.kind;
  const subkind = env.header.subkind ?? undefined;
  const actors = env.header.participants?.actors ?? [];
  const from = actors[0]?.id;
  const payloadType = env.payload?.type;
  const tone = kind === "commit" ? "var(--green)" : kind === "knowledge" ? "var(--yellow)" : "var(--accent)";

  return (
    <div className="flex items-baseline gap-2 border-b border-border/60 px-1 py-2 last:border-b-0">
      <span
        className="flex-shrink-0 rounded px-1.5 py-0.5 font-mono text-micro font-medium"
        style={{ color: tone, background: `color-mix(in srgb, ${tone} 12%, transparent)` }}
      >
        {kind}{subkind ? `:${subkind}` : ""}
      </span>
      {from && <span className="font-mono text-micro text-muted-foreground truncate">{from}</span>}
      {payloadType && <span className="text-micro text-faint truncate">{payloadType}</span>}
    </div>
  );
}

/** Read-only review of one episode: outcome, metrics, assignments, L9 chain. */
export function EpisodeDetail({ roomName, shortId }: { roomName: string; shortId: string }) {
  const [detail, setDetail] = useState<EpisodeDetailT | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchEpisode(roomName, shortId)
      .then(d => { if (!cancelled) { setDetail(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [roomName, shortId]);

  if (loading) {
    return <div className="px-5 py-8 text-center text-label text-muted-foreground">Loading chain…</div>;
  }
  if (!detail) {
    return <div className="px-5 py-8 text-center text-label text-muted-foreground">Episode not found</div>;
  }

  const state = detail.subkind ?? detail.outcome;
  const color = outcomeColor(state);
  const assignments = detail.assignments ?? {};
  const m = detail.metrics;

  return (
    <div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-b border-border px-5 py-4">
        <Meta label="Outcome">
          <span className="capitalize" style={{ color }}>{state}</span>
        </Meta>
        <Meta label="Participants">{detail.participants.join(", ") || "-"}</Meta>
        {detail.plan_file && (
          <Meta label="Plan"><span className="font-mono text-micro text-accent">{detail.plan_file}</span></Meta>
        )}
        {detail.updated_at && (
          <Meta label="Updated"><span className="tabular">{new Date(detail.updated_at).toLocaleString()}</span></Meta>
        )}
      </div>

      {m && (
        <div className="grid grid-cols-3 gap-2 border-b border-border px-5 py-4">
          <Stat label="MPC" value={m.mpc.toFixed(2)} title="Mutual proposal coherence" />
          <Stat label="GAR" value={m.gar.toFixed(2)} title="Genuine agreement ratio" />
          <Stat label="SCR" value={m.scr.toFixed(2)} title="Self-consistency ratio" />
        </div>
      )}

      {Object.keys(assignments).length > 0 && (
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2 text-micro uppercase tracking-wide text-faint">Agreement</div>
          <div className="flex flex-col gap-1">
            {Object.entries(assignments).map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-2 font-mono text-label">
                <span className="text-muted-foreground">{k}</span>
                <span className="text-faint">=</span>
                <span className="text-text">{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="px-5 py-4">
        <div className="mb-1 flex items-baseline gap-2">
          <span className="text-micro uppercase tracking-wide text-faint">L9 chain</span>
          <span className="text-micro tabular text-muted-foreground">{detail.messages.length} envelopes</span>
        </div>
        {detail.messages.length === 0 ? (
          <div className="py-4 text-center text-label text-muted-foreground">No envelopes recorded</div>
        ) : (
          <div>{detail.messages.map((env, i) => <EnvelopeRow key={i} env={env} />)}</div>
        )}
      </div>
    </div>
  );
}
