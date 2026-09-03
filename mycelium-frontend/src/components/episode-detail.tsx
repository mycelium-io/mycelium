// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { fetchEpisode, type EpisodeDetail as EpisodeDetailT, type L9Envelope } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";

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

/** A quality metric tile. The label is an acronym, so the tooltip spelling it
 *  out is the tile's only explanation — `aria-description` keeps it for readers
 *  that never hover. */
function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Tooltip content={hint}>
      <div
        aria-description={hint}
        className="flex flex-col gap-0.5 rounded-lg border border-border bg-surface px-3 py-2"
      >
        <span className="text-micro uppercase tracking-wide text-faint">{label}</span>
        <span className="font-mono text-label tabular text-text">{value}</span>
      </div>
    </Tooltip>
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
    let canceled = false;
    // Async fetch; the other setState calls are in its callbacks. This one is
    // the loading gate, which has to be raised before the fetch starts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetchEpisode(roomName, shortId)
      .then(d => { if (!canceled) { setDetail(d); setLoading(false); } })
      .catch(() => { if (!canceled) setLoading(false); });
    return () => { canceled = true; };
  }, [roomName, shortId]);

  if (loading) {
    return (
      <div className="px-5 py-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <Skeleton className="h-2.5 w-16" />
              <Skeleton className="h-3 w-24" />
            </div>
          ))}
        </div>
      </div>
    );
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
        {detail.updated_at && (
          <Meta label="Updated"><span className="tabular">{new Date(detail.updated_at).toLocaleString()}</span></Meta>
        )}
      </div>

      {m && (
        <div className="grid grid-cols-3 gap-2 border-b border-border px-5 py-4">
          <Stat label="MPC" value={m.mpc.toFixed(2)} hint="Mutual proposal coherence" />
          <Stat label="GAR" value={m.gar.toFixed(2)} hint="Genuine agreement ratio" />
          <Stat label="SCR" value={m.scr.toFixed(2)} hint="Self-consistency ratio" />
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
