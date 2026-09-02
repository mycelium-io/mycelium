// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Metrics — what this hub has actually done since it came up.
 *
 * Every number on this page is read from something the running stack produces:
 * the backend's in-process counters (`/api/observability`), the coordination
 * fabric and posture blocks of `/health`, and the episode records the aligner
 * writes per convening. Nothing is derived from a service the stack no longer
 * ships, and nothing is shown as `0` that is merely unmeasured — an untouched
 * counter reads `-`, and a panel with no data says what would put data in it.
 *
 *   <MetricsScreen />
 *     ├─ <HeaderBand />       uptime, cadence, pause
 *     ├─ <Kpi /> × 3          memory · fabric · cognition
 *     ├─ <FabricPanel />      SLIM node, posture, one row per live channel
 *     ├─ <EpisodesPanel />    negotiations across every room, and how they ended
 *     ├─ <MemoryPanel />      writes, retrieval hit rate, search latency
 *     ├─ <EmbeddingPanel />   the local model, and the spend it avoids
 *     ├─ <IndexerPanel />     filesystem → JSONL runs
 *     └─ <CognitionPanel />   Pi calls by operation and model
 */

import { useMemo, useState, type ReactNode } from "react";
import { Pause, Play } from "lucide-react";
import type { AuthStatus, CoordinationStatus, IdentityStatus } from "@/lib/api";
import { useNetworkStatus, useRooms } from "@/lib/room-data";
import {
  episodeState,
  rollupEpisodes,
  useBackendMetrics,
  useFleetEpisodes,
  type BackendMetrics,
  type EpisodeRollup,
  type FleetEpisode,
} from "@/lib/metrics-data";
import {
  fmtAgo,
  fmtDur,
  fmtMs,
  fmtNum,
  fmtPct,
  fmtUsd,
  histAvg,
  subCounters,
  type BackendHistogram,
} from "@/lib/metrics-format";

/** Cadences offered in the header. 5s is for watching something happen; 60s is
 *  for leaving the page open. */
const CADENCES = [5, 10, 30, 60] as const;

/** How many of the newest episodes the negotiations panel lists. */
const RECENT_EPISODES = 6;

// ── Atoms ────────────────────────────────────────────────────────────────────

function Caps({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`text-micro font-medium uppercase tracking-wide text-muted-foreground ${className}`}>
      {children}
    </div>
  );
}

function Dot({ color }: { color: string }) {
  return <span className="inline-block size-1.5 shrink-0 rounded-full" style={{ background: color }} />;
}

/** A titled card. Every section of the page is one of these, so a panel that has
 *  nothing to show still occupies its place and explains itself. */
function Panel({
  title,
  meta,
  children,
  className = "",
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 overflow-hidden rounded-xl border border-border bg-surface/40 ${className}`}>
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <Caps>{title}</Caps>
        {meta && <div className="flex items-center gap-1.5 text-micro text-muted-foreground">{meta}</div>}
      </header>
      {children}
    </section>
  );
}

/** The line a panel shows instead of a grid of dashes: what is missing, and the
 *  thing that would fill it. */
function Nothing({ children }: { children: ReactNode }) {
  return <p className="px-4 py-3 text-label leading-relaxed text-muted-foreground">{children}</p>;
}

/** One labelled figure inside a panel's grid. */
function Figure({
  label,
  value,
  color,
  hint,
}: {
  label: string;
  value: ReactNode;
  color?: string;
  hint?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 px-4 py-3" title={hint}>
      <Caps>{label}</Caps>
      <span className="font-mono text-ui font-semibold tabular" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

/** A responsive row of figures, hairlined into cells. */
function Figures({ children, cols = 4 }: { children: ReactNode; cols?: 3 | 4 | 5 }) {
  const wide = { 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-5" }[cols];
  return (
    <div className={`grid grid-cols-2 divide-x divide-y divide-border ${wide} sm:divide-y-0`}>
      {children}
    </div>
  );
}

/** count / avg / min / max for one backend histogram. */
function Latency({ label, h }: { label: string; h?: BackendHistogram }) {
  if (!h?.count) {
    return (
      <div className="flex items-baseline justify-between gap-3 border-t border-border px-4 py-2.5">
        <Caps>{label}</Caps>
        <span className="text-micro text-muted-foreground">no samples yet</span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1 border-t border-border px-4 py-2.5">
      <Caps>{label}</Caps>
      <div className="flex items-baseline gap-4 font-mono text-micro tabular">
        <span className="text-muted-foreground">
          n <span className="text-text">{fmtNum(h.count)}</span>
        </span>
        <span className="text-muted-foreground">
          avg <span className="text-text">{fmtMs(histAvg(h))}</span>
        </span>
        <span className="text-muted-foreground">
          min <span className="text-text">{fmtMs(h.min)}</span>
        </span>
        <span className="text-muted-foreground">
          max <span className="text-text">{fmtMs(h.max)}</span>
        </span>
      </div>
    </div>
  );
}

/** A footnote under a panel — the caveat that keeps a figure honest. */
function Note({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-border px-4 py-2 text-micro leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}

// ── Header band ──────────────────────────────────────────────────────────────

function HeaderBand({
  metrics,
  paused,
  setPaused,
  cadence,
  setCadence,
}: {
  metrics: BackendMetrics | null;
  paused: boolean;
  setPaused: (b: boolean) => void;
  cadence: number;
  setCadence: (s: number) => void;
}) {
  return (
    <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-border bg-paper px-5 py-1.5">
      <div className="flex items-center gap-2 font-mono text-micro text-muted-foreground">
        <Dot color={paused ? "var(--faint)" : "var(--green)"} />
        {metrics ? (
          <span>
            up <span className="text-text">{fmtDur(metrics.started_at)}</span>
            <span className="mx-1.5 text-faint">·</span>
            updated <span className="text-text">{fmtAgo(metrics.updated_at)}</span>
          </span>
        ) : (
          <span>connecting…</span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {CADENCES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={cadence === s}
              onClick={() => setCadence(s)}
              className={`rounded-md px-2 py-0.5 text-micro font-medium tabular transition-colors ${
                cadence === s
                  ? "bg-elevated text-text ring-1 ring-border"
                  : "text-muted-foreground hover:text-text"
              }`}
            >
              {s}s
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setPaused(!paused)}
          className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-micro font-medium text-muted-foreground transition-colors hover:text-text"
        >
          {paused ? <Play className="size-3" /> : <Pause className="size-3" />}
          {paused ? "Paused" : "Live"}
        </button>
      </div>
    </div>
  );
}

// ── KPI band ─────────────────────────────────────────────────────────────────

function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-xl border border-border bg-surface/40 px-5 py-4">
      <Caps>{label}</Caps>
      <div className="font-mono text-[28px] font-semibold leading-none tabular text-text">{value}</div>
      <div className="text-micro leading-snug text-muted-foreground">{sub}</div>
    </div>
  );
}

// ── Coordination fabric ──────────────────────────────────────────────────────

function identityColor(identity: IdentityStatus | null): string {
  if (!identity) return "var(--faint)";
  if (identity.status === "error") return "var(--red)";
  if (identity.status === "degraded") return "var(--yellow)";
  return "var(--green)";
}

function FabricPanel({
  coordination,
  identity,
  auth,
  loaded,
}: {
  coordination: CoordinationStatus | null;
  identity: IdentityStatus | null;
  auth: AuthStatus | null;
  loaded: boolean;
}) {
  const enabled = coordination?.slim_enabled ?? false;
  const rooms = coordination?.rooms ?? [];
  return (
    <Panel
      title="Coordination fabric"
      meta={
        <>
          <Dot color={coordination ? (enabled ? "var(--green)" : "var(--red)") : "var(--faint)"} />
          <span className="font-mono">{coordination?.endpoint ?? "…"}</span>
        </>
      }
    >
      <Figures cols={5}>
        <Figure label="Channels live" value={coordination?.channels_live ?? "-"} />
        <Figure
          label="Provisions"
          value={coordination ? `${coordination.provisions_ok}✓ ${coordination.provisions_failed}✗` : "-"}
          color={(coordination?.provisions_failed ?? 0) > 0 ? "var(--red)" : undefined}
        />
        <Figure
          label="Invite failures"
          value={coordination?.invite_failures ?? "-"}
          color={(coordination?.invite_failures ?? 0) > 0 ? "var(--yellow)" : undefined}
        />
        <Figure
          label="Identity"
          value={identity?.mode ?? "-"}
          color={identityColor(identity)}
          hint={identity?.message}
        />
        <Figure
          label="API gate"
          value={auth ? (auth.enabled ? "on" : "off") : "-"}
          hint={auth?.issuers.length ? `issuers: ${auth.issuers.join(", ")}` : undefined}
        />
      </Figures>

      {rooms.length === 0 ? (
        <Nothing>
          {loaded
            ? "No room channel is provisioned. A channel comes up the first time a room is joined or posted to."
            : "Reading the fabric…"}
        </Nothing>
      ) : (
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full min-w-[560px] border-collapse text-micro">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Room</th>
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Channel</th>
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Members</th>
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Episode</th>
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Invites</th>
                <th className="px-4 py-2 font-medium uppercase tracking-wide">Inbox</th>
                <th className="px-4 py-2 text-right font-medium uppercase tracking-wide">Errors</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((r) => {
                const errors = r.receive_errors + r.transient_errors + r.reserve_failures;
                const healthy = r.provisioned && r.persister_alive;
                return (
                  <tr key={r.room} className="border-b border-border/50 last:border-b-0">
                    <td className="px-4 py-2 font-medium text-text">{r.room}</td>
                    <td className="px-4 py-2">
                      <span className="flex items-center gap-1.5 text-muted-foreground">
                        <Dot color={healthy ? "var(--green)" : "var(--yellow)"} />
                        {r.provisioned ? (r.persister_alive ? "live" : "no persister") : "pending"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {r.members.length > 0 ? r.members.join(", ") : "—"}
                    </td>
                    <td className="px-4 py-2" style={{ color: r.episode_active ? "var(--accent)" : undefined }}>
                      <span className={r.episode_active ? "" : "text-muted-foreground"}>
                        {r.episode_active ? "active" : "idle"}
                      </span>
                    </td>
                    <td
                      className="px-4 py-2 tabular text-muted-foreground"
                      style={{ color: r.deferred_invites > 0 ? "var(--yellow)" : undefined }}
                    >
                      {r.deferred_invites}
                    </td>
                    <td className="px-4 py-2 tabular text-muted-foreground">
                      {r.reserves} held{r.reserve_skipped > 0 ? ` · ${r.reserve_skipped} skipped` : ""}
                    </td>
                    <td
                      className="px-4 py-2 text-right tabular"
                      style={{ color: errors > 0 ? "var(--red)" : "var(--muted-foreground)" }}
                    >
                      {errors}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

// ── Negotiations ─────────────────────────────────────────────────────────────

function stateColor(state: string): string {
  if (state === "converged" || state === "resolved") return "var(--green)";
  if (state === "rejected") return "var(--yellow)";
  return "var(--accent)";
}

function fmtRatio(n: number | null): string {
  return n == null ? "-" : n.toFixed(2);
}

function EpisodesPanel({ rollup, rooms }: { rollup: EpisodeRollup; rooms: number }) {
  const recent = rollup.recent.slice(0, RECENT_EPISODES);
  return (
    <Panel
      title="Negotiations"
      meta={<span>{rooms === 1 ? "1 room" : `${rooms} rooms`}</span>}
    >
      {rollup.total === 0 ? (
        <Nothing>
          No episode recorded yet. Each convening of the aligner —{" "}
          <span className="font-mono text-text">mycelium engine invoke aligner …</span> — is one
          episode, and lands here with how it ended.
        </Nothing>
      ) : (
        <>
          <Figures cols={5}>
            <Figure label="Episodes" value={fmtNum(rollup.total)} />
            <Figure label="Converged" value={fmtNum(rollup.converged)} color="var(--green)" />
            <Figure
              label="Rejected"
              value={fmtNum(rollup.rejected)}
              color={rollup.rejected > 0 ? "var(--yellow)" : undefined}
            />
            <Figure label="Open" value={fmtNum(rollup.open)} color={rollup.open > 0 ? "var(--accent)" : undefined} />
            <Figure label="Work rows" value={fmtNum(rollup.tasks)} />
          </Figures>

          <Figures cols={5}>
            <Figure
              label="Avg agents"
              value={rollup.avgParticipants == null ? "-" : rollup.avgParticipants.toFixed(1)}
            />
            <Figure label="MPC" value={fmtRatio(rollup.mpc)} hint="Mean posterior confidence" />
            <Figure label="GAR" value={fmtRatio(rollup.gar)} hint="Genuine agreement ratio" />
            <Figure label="SCR" value={fmtRatio(rollup.scr)} hint="Sycophantic collapse risk" />
            <Figure
              label="Provenance"
              value={fmtRatio(rollup.provenance)}
              hint="(1 - SCR) x GAR — agreement discounted by how much of it was deference"
            />
          </Figures>

          <ul className="border-t border-border">
            {recent.map((ep) => (
              <RecentEpisode key={`${ep.room}/${ep.short_id}`} episode={ep} />
            ))}
          </ul>

          <Note>
            Quality ratios are averaged over the {rollup.scored}{" "}
            {rollup.scored === 1 ? "episode" : "episodes"} that committed with L9 metrics; an
            episode still in progress contributes to the counts above but not to the ratios.
          </Note>
        </>
      )}
    </Panel>
  );
}

function RecentEpisode({ episode }: { episode: FleetEpisode }) {
  const state = episodeState(episode);
  return (
    <li className="flex items-baseline gap-3 border-b border-border/50 px-4 py-2 text-micro last:border-b-0">
      <Dot color={stateColor(state)} />
      <span className="shrink-0 font-mono text-muted-foreground">{episode.room}</span>
      <span className="min-w-0 flex-1 truncate text-text">{episode.topic || episode.short_id}</span>
      <span className="shrink-0 text-muted-foreground">{state}</span>
      <span className="shrink-0 tabular text-faint">{fmtAgo(episode.updated_at)}</span>
    </li>
  );
}

// ── Backend counter panels ───────────────────────────────────────────────────

function MemoryPanel({
  memory,
  search,
}: {
  memory: Record<string, number> | undefined;
  search?: BackendHistogram;
}) {
  const searches = memory?.searches ?? 0;
  const writes = memory?.writes;
  return (
    <Panel title="Memory & retrieval">
      {writes == null && searches === 0 ? (
        <Nothing>
          Nothing written or searched since the hub came up. Counters start at the first{" "}
          <span className="font-mono text-text">memory set</span>.
        </Nothing>
      ) : (
        <Figures cols={4}>
          <Figure label="Writes" value={fmtNum(writes)} />
          <Figure label="Embedded" value={fmtNum(memory?.writes_embedded)} />
          <Figure label="Searches" value={fmtNum(memory?.searches)} />
          <Figure label="Hit rate" value={fmtPct(memory?.search_hits, searches)} hint="Searches that returned at least one result" />
        </Figures>
      )}
      <Latency label="Search latency" h={search} />
    </Panel>
  );
}

function EmbeddingPanel({
  embeddings,
  latency,
}: {
  embeddings: Record<string, number> | undefined;
  latency?: BackendHistogram;
}) {
  const computed = embeddings?.computed;
  return (
    <Panel title="Embeddings">
      {computed == null ? (
        <Nothing>
          The local model has not been asked for a vector yet. Writing or searching a memory is what
          asks it.
        </Nothing>
      ) : (
        <Figures cols={3}>
          <Figure label="Computed" value={fmtNum(computed)} />
          <Figure label="Est. tokens" value={fmtNum(embeddings?.estimated_tokens)} />
          <Figure
            label="Spend avoided"
            value={fmtUsd(embeddings?.estimated_cost_avoided_usd)}
            color="var(--green)"
            hint="What these embeddings would have cost against a hosted embedding API"
          />
        </Figures>
      )}
      <Latency label="Embedding latency" h={latency} />
      <Note>
        Vectors are computed in-process by <span className="font-mono">BAAI/bge-small-en-v1.5</span>,
        so nothing here leaves the hub and the avoided spend is an estimate against a hosted API&apos;s
        list price.
      </Note>
    </Panel>
  );
}

function IndexerPanel({
  indexer,
  duration,
}: {
  indexer: Record<string, number> | undefined;
  duration?: BackendHistogram;
}) {
  const runs = indexer?.runs;
  const errors = indexer?.errors ?? 0;
  return (
    <Panel title="Indexer">
      {runs == null ? (
        <Nothing>No indexing run yet — the index is rebuilt as memories are written.</Nothing>
      ) : (
        <Figures cols={4}>
          <Figure label="Runs" value={fmtNum(runs)} />
          <Figure label="Indexed" value={fmtNum(indexer?.files_indexed)} />
          <Figure label="Pruned" value={fmtNum(indexer?.files_pruned)} />
          <Figure
            label="Errors"
            value={fmtNum(errors)}
            color={errors > 0 ? "var(--red)" : undefined}
            hint={errors > 0 ? "mycelium logs --grep indexer" : undefined}
          />
        </Figures>
      )}
      <Latency label="Run duration" h={duration} />
    </Panel>
  );
}

function CognitionPanel({
  llm,
  histograms,
}: {
  llm: Record<string, number> | undefined;
  histograms: Record<string, BackendHistogram>;
}) {
  const calls = llm?.calls;
  const errors = llm?.errors ?? 0;
  const operations = subCounters(llm, "by_operation");
  const models = subCounters(llm, "by_model", true);
  return (
    <Panel title="Cognition">
      {calls == null ? (
        <Nothing>
          No Pi turn has run yet. The aligner&apos;s brain, the task compiler and the health probe all
          land here.
        </Nothing>
      ) : (
        <>
          <Figures cols={4}>
            <Figure label="Calls" value={fmtNum(calls)} />
            <Figure
              label="Errors"
              value={fmtNum(errors)}
              color={errors > 0 ? "var(--red)" : undefined}
            />
            <Figure label="Failure rate" value={fmtPct(errors, calls)} />
            <Figure label="Models" value={models.length || "-"} hint={models.map(([m]) => m).join(", ")} />
          </Figures>

          {operations.length > 0 && (
            <ul className="border-t border-border">
              {operations.map(([op, n]) => (
                <li
                  key={op}
                  className="flex items-baseline justify-between gap-3 border-b border-border/50 px-4 py-2 text-micro last:border-b-0"
                >
                  <span className="font-mono text-text">{op}</span>
                  <span className="flex items-baseline gap-4 font-mono tabular text-muted-foreground">
                    <span>
                      {fmtNum(n)} {n === 1 ? "call" : "calls"}
                    </span>
                    <span>{fmtMs(histAvg(histograms[`llm.latency_ms.${op}`]))} avg</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <Latency label="Call latency" h={histograms["llm.latency_ms"]} />
      <Note>
        Cognition runs through the <span className="font-mono">pi</span> binary, which does not
        report per-turn token usage — so calls, failures and latency are counted here and spend is
        not claimed.
      </Note>
    </Panel>
  );
}

// ── Backend unreachable ──────────────────────────────────────────────────────

function BackendDown() {
  return (
    <div className="flex flex-1 items-center justify-center p-10">
      <div className="max-w-lg rounded-xl border border-border bg-surface/40 px-7 py-6">
        <Caps className="text-yellow">Backend unreachable</Caps>
        <p className="mt-2 text-label leading-relaxed text-muted-foreground">
          Nothing answered <span className="font-mono text-text">GET /api/observability</span>. Bring
          the stack up with <span className="font-mono text-text">mycelium up</span>, or run{" "}
          <span className="font-mono text-text">mycelium doctor</span> to find out what is holding it
          down.
        </p>
      </div>
    </div>
  );
}

// ── Screen ───────────────────────────────────────────────────────────────────

export function MetricsScreen() {
  const [paused, setPaused] = useState(false);
  const [cadence, setCadence] = useState<number>(10);
  // SWR reads 0 as "do not poll", so pausing is the same control as the cadence.
  const refreshInterval = paused ? 0 : cadence * 1000;

  const { metrics, loading } = useBackendMetrics(refreshInterval);
  const { network, loading: networkLoading } = useNetworkStatus({ refreshInterval });
  const { rooms } = useRooms({ refreshInterval });
  const roomNames = useMemo(() => rooms.map((r) => r.name), [rooms]);
  const { episodes } = useFleetEpisodes(roomNames, refreshInterval);
  const rollup = useMemo(() => rollupEpisodes(episodes), [episodes]);

  const counters = metrics?.counters ?? {};
  const histograms = metrics?.histograms ?? {};
  const coordination = network?.coordination ?? null;

  const membersPresent = useMemo(
    () => new Set((coordination?.rooms ?? []).flatMap((r) => r.members)).size,
    [coordination],
  );
  const episodesActive = (coordination?.rooms ?? []).filter((r) => r.episode_active).length;

  if (!metrics && !loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <HeaderBand
          metrics={null}
          paused={paused}
          setPaused={setPaused}
          cadence={cadence}
          setCadence={setCadence}
        />
        <BackendDown />
      </div>
    );
  }

  const memory = counters.memory;
  const llmCalls = counters.llm?.calls;
  const searches = memory?.searches ?? 0;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <HeaderBand
        metrics={metrics}
        paused={paused}
        setPaused={setPaused}
        cadence={cadence}
        setCadence={setCadence}
      />

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 p-5">
          <div className="grid gap-4 md:grid-cols-3">
            <Kpi
              label="Memory"
              value={fmtNum(memory?.writes)}
              sub={
                <>
                  written <span className="text-faint">·</span> {fmtNum(searches)} searches{" "}
                  <span className="text-faint">·</span> {fmtPct(memory?.search_hits, searches)} hit
                  rate
                </>
              }
            />
            <Kpi
              label="Fabric"
              value={coordination?.channels_live ?? "-"}
              sub={
                <>
                  channels live <span className="text-faint">·</span> {membersPresent} present{" "}
                  <span className="text-faint">·</span> {episodesActive} negotiating
                </>
              }
            />
            <Kpi
              label="Cognition"
              value={fmtNum(llmCalls)}
              sub={
                <>
                  Pi calls <span className="text-faint">·</span> {fmtNum(counters.llm?.errors ?? 0)}{" "}
                  failed <span className="text-faint">·</span>{" "}
                  {fmtMs(histAvg(histograms["llm.latency_ms"]))} avg
                </>
              }
            />
          </div>

          <FabricPanel
            coordination={coordination}
            identity={network?.identity ?? null}
            auth={network?.auth ?? null}
            loaded={!networkLoading}
          />

          <EpisodesPanel rollup={rollup} rooms={roomNames.length} />

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <MemoryPanel memory={memory} search={histograms["memory.search_latency_ms"]} />
            <EmbeddingPanel
              embeddings={counters.embeddings}
              latency={histograms["embeddings.latency_ms"]}
            />
            <IndexerPanel indexer={counters.indexer} duration={histograms["indexer.duration_ms"]} />
            <CognitionPanel llm={counters.llm} histograms={histograms} />
          </div>
        </div>
      </div>
    </div>
  );
}
