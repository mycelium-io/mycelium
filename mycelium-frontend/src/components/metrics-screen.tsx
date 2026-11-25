// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Metrics — what this hub has actually done since it came up.
 *
 * Every number on this page is read from something the running stack produces:
 * the backend's in-process counters (`/api/observability`) and the episode
 * records the conductor writes per run. Nothing is derived from a service the stack no longer
 * ships, and nothing is shown as `0` that is merely unmeasured — an untouched
 * counter reads `-`, and a panel with no data says what would put data in it.
 *
 *   <MetricsScreen />
 *     ├─ <HeaderBand />       the Usage | System tabs, uptime, cadence, pause
 *     ├─ Usage tab            <UsageView />: what the hub is used for, its KPIs;
 *     │                       <ActivityPanel />: one room's days, streak and who did what
 *     └─ System tab
 *         ├─ <Kpi /> × 2          memory · cognition
 *         ├─ <EpisodesPanel />    negotiations across every room, and how they ended
 *         ├─ <MemoryPanel />      writes, retrieval hit rate, search latency
 *         ├─ <EmbeddingPanel />   the local model, and the spend it avoids
 *         ├─ <IndexerPanel />     filesystem → JSONL runs
 *         └─ <CognitionPanel />   Pi calls by operation and model
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Pause, Play } from "lucide-react";
import { Dot, Figure, Figures, Label, Note, Nothing, Panel } from "@/components/metrics-parts";
import { UsageView } from "@/components/usage-view";
import { ActivityPanel } from "@/components/activity-log";
import { useRooms } from "@/lib/room-data";
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

/** count / avg / min / max for one backend histogram. */
function Latency({ label, h }: { label: string; h?: BackendHistogram }) {
  if (!h?.count) {
    return (
      <div className="flex items-baseline justify-between gap-3 border-t border-border px-4 py-2.5">
        <Label>{label}</Label>
        <span className="text-micro text-muted-foreground">no samples yet</span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-1 border-t border-border px-4 py-2.5">
      <Label>{label}</Label>
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


// ── Header band ──────────────────────────────────────────────────────────────

type Tab = "usage" | "system";
const TABS: { id: Tab; label: string }[] = [
  { id: "usage", label: "Usage" },
  { id: "system", label: "System" },
];
const TAB_KEY = "mycelium.metrics.tab";

function HeaderBand({
  metrics,
  paused,
  setPaused,
  cadence,
  setCadence,
  tab,
  setTab,
}: {
  metrics: BackendMetrics | null;
  paused: boolean;
  setPaused: (b: boolean) => void;
  cadence: number;
  setCadence: (s: number) => void;
  tab: Tab;
  setTab: (t: Tab) => void;
}) {
  return (
    <div className="flex h-8 shrink-0 items-center gap-x-4 border-b border-border bg-surface pr-4">
      {/* Flat tabs, as the room's Channel and Board are drawn. */}
      <div role="tablist" aria-label="Metrics" className="flex h-full items-stretch">
        {TABS.map(t => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px flex items-center border-r border-border px-3 text-label transition-colors ${
              tab === t.id ? "bg-paper text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
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

      <div className="ml-auto flex items-center gap-3 text-micro text-muted-foreground">
        <span className="text-faint">every</span>
        {CADENCES.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={cadence === s}
            onClick={() => setCadence(s)}
            className={`tabular transition-colors hover:text-text ${cadence === s ? "text-text" : ""}`}
          >
            {s}s
          </button>
        ))}
        <span aria-hidden className="h-3 w-px bg-border" />
        <button
          type="button"
          onClick={() => setPaused(!paused)}
          className="flex items-center gap-1.5 transition-colors hover:text-text"
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
    <div className="flex min-w-0 flex-col gap-1 px-4 py-3">
      <Label>{label}</Label>
      <div className="font-mono text-xl font-medium leading-none tabular text-text">{value}</div>
      <div className="text-micro leading-snug text-muted-foreground">{sub}</div>
    </div>
  );
}

// ── Negotiations ─────────────────────────────────────────────────────────────

function stateColor(state: string): string {
  if (state === "converged" || state === "resolved") return "var(--green)";
  if (state === "rejected") return "var(--yellow)";
  return "var(--accent)";
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
          No episode recorded yet. Each run of the conductor —{" "}
          <span className="font-mono text-text">mycelium board coordinate &lt;row&gt; conductor &quot;review …&quot;</span> — is
          one episode, and lands here with how it ended.
        </Nothing>
      ) : (
        <>
          <Figures cols={6}>
            <Figure label="Episodes" value={fmtNum(rollup.total)} />
            <Figure label="Converged" value={fmtNum(rollup.converged)} color="var(--green)" />
            <Figure
              label="Rejected"
              value={fmtNum(rollup.rejected)}
              color={rollup.rejected > 0 ? "var(--yellow)" : undefined}
            />
            <Figure label="Open" value={fmtNum(rollup.open)} color={rollup.open > 0 ? "var(--accent)" : undefined} />
            <Figure label="Work rows" value={fmtNum(rollup.tasks)} />
            <Figure
              label="Avg agents"
              value={rollup.avgParticipants == null ? "-" : rollup.avgParticipants.toFixed(1)}
            />
          </Figures>

          <ul className="border-t border-border">
            {recent.map((ep) => (
              <RecentEpisode key={`${ep.room}/${ep.short_id}`} episode={ep} />
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

function RecentEpisode({ episode }: { episode: FleetEpisode }) {
  const state = episodeState(episode);
  return (
    <li className="flex h-7 items-center gap-3 px-4 text-micro">
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
            hint={errors > 0 ? "mycelium logs mycelium-backend | grep indexer" : undefined}
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
          No Pi turn has run yet. The conductor&apos;s steps, the personas and the health probe all land
          here.
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
      <div className="max-w-lg">
        <Label className="text-yellow">Backend unreachable</Label>
        <p className="mt-2 text-label leading-relaxed text-muted-foreground">
          Nothing answered <span className="font-mono text-text">GET /api/observability</span>. Open the
          Mycelium app (or run <span className="font-mono text-text">mycelium up</span> for the
          Docker stack), or run{" "}
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
  const { rooms } = useRooms({ refreshInterval });
  const roomNames = useMemo(() => rooms.map((r) => r.name), [rooms]);
  const { episodes } = useFleetEpisodes(roomNames, refreshInterval);
  const rollup = useMemo(() => rollupEpisodes(episodes), [episodes]);
  // Which tab, remembered per browser; Usage first, since it's the question
  // most people open this page with.
  const [tab, setTabState] = useState<Tab>("usage");
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(TAB_KEY);
      // localStorage is client-only; reading it at init would mismatch the SSR render.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved === "usage" || saved === "system") setTabState(saved);
    } catch {
      // Remembering the tab is a convenience; the page works without it.
    }
  }, []);
  const setTab = (next: Tab) => {
    setTabState(next);
    try {
      window.localStorage.setItem(TAB_KEY, next);
    } catch {
      // As above.
    }
  };
  const header = (m: BackendMetrics | null) => (
    <HeaderBand
      metrics={m}
      paused={paused}
      setPaused={setPaused}
      cadence={cadence}
      setCadence={setCadence}
      tab={tab}
      setTab={setTab}
    />
  );

  const counters = metrics?.counters ?? {};
  const histograms = metrics?.histograms ?? {};

  if (!metrics && !loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        {header(null)}
        <BackendDown />
      </div>
    );
  }

  const memory = counters.memory;
  const llmCalls = counters.llm?.calls;
  const searches = memory?.searches ?? 0;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {header(metrics)}

      <div className="flex-1 overflow-y-auto">
        {tab === "usage" ? (
          <div className="mx-auto flex max-w-5xl flex-col py-2">
            <UsageView refreshInterval={refreshInterval} />
            <ActivityPanel rooms={roomNames} />
          </div>
        ) : (
        <div className="mx-auto flex max-w-5xl flex-col py-2">
          <div className="grid md:grid-cols-2">
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

          <EpisodesPanel rollup={rollup} rooms={roomNames.length} />

          <div className="grid items-start lg:grid-cols-2">
            <MemoryPanel memory={memory} search={histograms["memory.search_latency_ms"]} />
            <EmbeddingPanel
              embeddings={counters.embeddings}
              latency={histograms["embeddings.latency_ms"]}
            />
            <IndexerPanel indexer={counters.indexer} duration={histograms["indexer.duration_ms"]} />
            <CognitionPanel llm={counters.llm} histograms={histograms} />
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
