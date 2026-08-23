// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  fetchBackendMetrics: vi.fn(),
  fetchNetworkStatus: vi.fn(),
  fetchRooms: vi.fn(),
  fetchEpisodes: vi.fn(),
  logFetchError: () => () => undefined,
}));

import { MetricsScreen } from "@/components/metrics-screen";
import {
  fetchBackendMetrics,
  fetchEpisodes,
  fetchNetworkStatus,
  fetchRooms,
  type EpisodeSummary,
  type NetworkStatus,
  type Room,
} from "@/lib/api";
import type { BackendMetrics } from "@/lib/metrics-data";

const metricsRead = vi.mocked(fetchBackendMetrics);
const networkRead = vi.mocked(fetchNetworkStatus);
const roomsRead = vi.mocked(fetchRooms);
const episodesRead = vi.mocked(fetchEpisodes);

function backend(overrides: Partial<BackendMetrics> = {}): BackendMetrics {
  return {
    started_at: new Date(Date.now() - 3_600_000).toISOString(),
    updated_at: new Date().toISOString(),
    counters: {
      memory: { writes: 148, writes_embedded: 140, searches: 96, search_hits: 72 },
      embeddings: { computed: 512, estimated_tokens: 31_400, estimated_cost_avoided_usd: 0.000628 },
      indexer: { runs: 34, files_indexed: 148, files_pruned: 3, errors: 0 },
      llm: {
        calls: 41,
        errors: 1,
        "by_operation.task_compile": 12,
        "by_operation.task_compile.input_tokens": 0,
        "by_operation.health_probe": 29,
        "by_model.anthropic/claude-sonnet-4-6": 41,
      },
    },
    histograms: {
      "memory.search_latency_ms": { count: 96, sum: 1920, min: 8, max: 61 },
      "llm.latency_ms": { count: 41, sum: 82_000, min: 810, max: 9240 },
    },
    ...overrides,
  };
}

function network(): NetworkStatus {
  return {
    coordination: {
      endpoint: "http://mycelium-slim:46357",
      slim_enabled: true,
      channels_live: 1,
      provisions_ok: 1,
      provisions_failed: 0,
      invite_failures: 0,
      rooms: [
        {
          room: "atlas-migration",
          provisioned: true,
          persister_alive: true,
          members: ["planner", "avery"],
          pending_invites: 0,
          episode_active: true,
          reserves: 3,
          reserve_failures: 0,
          reserve_skipped: 0,
          receive_errors: 0,
          transient_errors: 0,
        },
      ],
    },
    identity: { status: "ok", mode: "psk", message: "psk" },
    auth: { enabled: false, issuers: [], localhost_bypass: true, audience: null },
  };
}

function episode(overrides: Partial<EpisodeSummary> = {}): EpisodeSummary {
  return {
    short_id: "ep-1",
    episode: "urn:ioc:episode:ep-1",
    topic: "cutover window",
    outcome: "converged",
    subkind: "converged",
    participants: ["planner", "avery"],
    metrics: { mpc: 0.82, gar: 0.75, scr: 0.1, provenance_weight: 0.68 },
    assignments: null,
    tasks: ["work/cutover", "work/rollback"],
    message_count: 14,
    updated_at: new Date().toISOString(),
    updated_by: "aligner",
    ...overrides,
  };
}

function room(name: string): Room {
  return { name, created_at: new Date().toISOString(), is_persistent: true };
}

beforeEach(() => {
  vi.clearAllMocks();
  metricsRead.mockResolvedValue(backend());
  networkRead.mockResolvedValue(network());
  roomsRead.mockResolvedValue([room("atlas-migration")]);
  episodesRead.mockResolvedValue([episode()]);
});

/** The panel card carrying a title, so a figure is asserted where it lives
 *  rather than anywhere on a page full of numbers. A KPI can share a panel's
 *  wording (`Cognition`), so only a match inside a `<section>` counts. */
function panel(title: string): HTMLElement {
  const sections = screen
    .getAllByText(title)
    .map((el) => el.closest("section"))
    .filter((el): el is HTMLElement => el !== null);
  if (sections.length !== 1) throw new Error(`${sections.length} panels titled "${title}"`);
  return sections[0];
}

describe("<MetricsScreen />", () => {
  it("draws the counters the backend actually reports", async () => {
    renderWithSWR(<MetricsScreen />);

    await screen.findByText("Memory & retrieval");
    const memory = panel("Memory & retrieval");
    expect(within(memory).getByText("148")).toBeInTheDocument();
    // 72 of 96 searches returned something.
    expect(within(memory).getByText("75%")).toBeInTheDocument();

    const embeddings = panel("Embeddings");
    expect(within(embeddings).getByText("512")).toBeInTheDocument();
    expect(within(embeddings).getByText("$0.0006")).toBeInTheDocument();
  });

  it("names each Pi operation rather than a spend it cannot measure", async () => {
    renderWithSWR(<MetricsScreen />);

    await screen.findByText("task_compile");
    const cognition = panel("Cognition");
    expect(within(cognition).getByText("task_compile")).toBeInTheDocument();
    expect(within(cognition).getByText("health_probe")).toBeInTheDocument();
    // The nested per-operation token counter is that operation's own total, not
    // an operation of its own.
    expect(within(cognition).queryByText("task_compile.input_tokens")).toBeNull();
    expect(within(cognition).getByText(/does not\s+report per-turn token usage/)).toBeInTheDocument();
  });

  it("reports the coordination fabric room by room", async () => {
    renderWithSWR(<MetricsScreen />);

    await screen.findByText("Coordination fabric");
    const fabric = panel("Coordination fabric");
    expect(within(fabric).getByText("http://mycelium-slim:46357")).toBeInTheDocument();
    expect(within(fabric).getByText("psk")).toBeInTheDocument();
    expect(within(fabric).getByText("atlas-migration")).toBeInTheDocument();
    expect(within(fabric).getByText("planner, avery")).toBeInTheDocument();
    expect(within(fabric).getByText("active")).toBeInTheDocument();
  });

  it("rolls every room's episodes up into how the negotiations ended", async () => {
    roomsRead.mockResolvedValue([room("atlas-migration"), room("pricing")]);
    episodesRead.mockImplementation(async (name: string) =>
      name === "atlas-migration"
        ? [episode()]
        : [
            episode({
              short_id: "ep-2",
              topic: "list price floor",
              subkind: "rejected",
              outcome: "rejected",
              metrics: null,
              tasks: [],
            }),
          ],
    );

    renderWithSWR(<MetricsScreen />);

    await screen.findByText("2 rooms");
    const negotiations = panel("Negotiations");
    expect(within(negotiations).getByText("2 rooms")).toBeInTheDocument();
    // Two episodes, one of each outcome, and only the converged one is scored.
    expect(within(negotiations).getByText("0.82")).toBeInTheDocument();
    expect(within(negotiations).getByText(/averaged over the 1 episode\b/)).toBeInTheDocument();
    expect(within(negotiations).getByText("cutover window")).toBeInTheDocument();
  });

  it("says what would fill a panel rather than drawing zeros", async () => {
    metricsRead.mockResolvedValue(backend({ counters: {}, histograms: {} }));
    episodesRead.mockResolvedValue([]);

    renderWithSWR(<MetricsScreen />);

    expect(await screen.findByText(/No episode recorded yet/)).toBeInTheDocument();
    expect(screen.getByText(/has not been asked for a vector yet/)).toBeInTheDocument();
    expect(screen.getByText(/No indexing run yet/)).toBeInTheDocument();
    expect(screen.getAllByText("no samples yet").length).toBeGreaterThan(0);
  });

  it("reports an unreachable hub instead of an empty dashboard", async () => {
    metricsRead.mockResolvedValue(null);

    renderWithSWR(<MetricsScreen />);

    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
    expect(screen.queryByText("Coordination fabric")).toBeNull();
  });
});
