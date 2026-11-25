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
  fetchUsage: vi.fn(),
  // A room's activity on the Usage tab: its messages, memories and roster.
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchMemorySummaries: vi.fn().mockResolvedValue([]),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomMembers: vi.fn().mockResolvedValue({ members: [], floors: [] }),
  fetchRoomPeople: vi.fn().mockResolvedValue({ people: [], agents: [], engines: [], others: [] }),
  logFetchError: () => () => undefined,
}));

import { MetricsScreen } from "@/components/metrics-screen";
import { usageKpis } from "@/mocks/fixtures";
import {
  fetchBackendMetrics,
  fetchEpisodes,
  fetchNetworkStatus,
  fetchRooms,
  fetchUsage,
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
    auth: { enabled: false, issuers: [], localhost_bypass: true, audience: null },
  };
}

function episode(overrides: Partial<EpisodeSummary> = {}): EpisodeSummary {
  return {
    short_id: "ep-1",
    episode: "urn:mycelium:episode:demo:ep-1",
    topic: "cutover window",
    outcome: "converged",
    subkind: "converged",
    participants: ["planner", "avery"],
    assignments: null,
    tasks: ["work/cutover", "work/rollback"],
    message_count: 14,
    updated_at: new Date().toISOString(),
    updated_by: "conductor",
    ...overrides,
  };
}

function room(name: string): Room {
  return { name, created_at: new Date().toISOString(), is_persistent: true };
}

beforeEach(() => {
  vi.clearAllMocks();
  // These tests are about the System tab; the Usage tab has its own below.
  window.localStorage.setItem("mycelium.metrics.tab", "system");
  vi.mocked(fetchUsage).mockResolvedValue(usageKpis(30));
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
  it("opens on what the hub is used for, and keeps the system one tab away", async () => {
    window.localStorage.removeItem("mycelium.metrics.tab");
    renderWithSWR(<MetricsScreen />);

    expect(await screen.findByText("Ways of working")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Usage" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Memory & retrieval")).not.toBeInTheDocument();

    screen.getByRole("tab", { name: "System" }).click();
    expect(await screen.findByText("Memory & retrieval")).toBeInTheDocument();
    expect(window.localStorage.getItem("mycelium.metrics.tab")).toBe("system");
  });

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
              tasks: [],
            }),
          ],
    );

    renderWithSWR(<MetricsScreen />);

    await screen.findByText("2 rooms");
    const negotiations = panel("Negotiations");
    expect(within(negotiations).getByText("2 rooms")).toBeInTheDocument();
    // Two episodes from two rooms, one of each outcome, both in the recent list.
    expect(within(negotiations).getByText("cutover window")).toBeInTheDocument();
    expect(within(negotiations).getByText("list price floor")).toBeInTheDocument();
    expect(within(negotiations).getByText("2.0")).toBeInTheDocument();
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
    expect(screen.queryByText("Memory & retrieval")).toBeNull();
  });
});
