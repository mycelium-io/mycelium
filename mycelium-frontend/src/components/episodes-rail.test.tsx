// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EpisodeSummary } from "@/lib/api";

vi.mock("@/components/episode-detail", () => ({
  EpisodeDetail: ({ shortId }: { shortId: string }) => (
    <div data-testid="episode-detail">{shortId}</div>
  ),
}));

vi.mock("@/lib/api", () => ({
  fetchEpisode: vi.fn().mockResolvedValue(null),
}));

import { fetchEpisode } from "@/lib/api";
import { EpisodesRail } from "@/components/episodes-rail";

function episode(shortId: string): EpisodeSummary {
  return {
    short_id: shortId,
    episode: `urn:ioc:mycelium:episode:atlas:${shortId}`,
    topic: "cutover window",
    outcome: "converged",
    subkind: "converged",
    participants: ["alice"],
    metrics: null,
    assignments: null,
    plan_file: null,
    message_count: 3,
    updated_at: "2026-08-04T10:00:00Z",
    updated_by: "aligner",
  };
}

const listed: EpisodeSummary[] = [episode("e4f1a2")];

vi.mock("@/lib/room-data", () => ({
  useRoomEpisodes: () => ({ episodes: listed, loading: false }),
}));

describe("<EpisodesRail /> focus requests", () => {
  beforeEach(() => {
    vi.mocked(fetchEpisode).mockClear();
  });

  it("opens the drawer on an episode named by a clicked chat tag", async () => {
    renderWithSWR(
      <EpisodesRail roomName="atlas" focusEpisode={{ shortId: "e4f1a2", nonce: 1 }} />,
    );

    expect(await screen.findByTestId("episode-detail")).toHaveTextContent("e4f1a2");
    // The listed episode answers the request; no detail fetch is needed.
    expect(fetchEpisode).not.toHaveBeenCalled();
  });

  it("reopens a drawer the reader closed when the same tag is clicked again", async () => {
    const { rerender } = renderWithSWR(
      <EpisodesRail roomName="atlas" focusEpisode={{ shortId: "e4f1a2", nonce: 1 }} />,
    );
    await screen.findByTestId("episode-detail");

    await act(async () => {
      screen.getByRole("button", { name: "Close" }).click();
    });
    expect(screen.queryByTestId("episode-detail")).not.toBeInTheDocument();

    // A second click on the same tag is a request of its own — the nonce is
    // what distinguishes it from the one already answered.
    rerender(<EpisodesRail roomName="atlas" focusEpisode={{ shortId: "e4f1a2", nonce: 2 }} />);
    expect(await screen.findByTestId("episode-detail")).toHaveTextContent("e4f1a2");
  });

  it("falls back to the detail endpoint for an episode past the list", async () => {
    vi.mocked(fetchEpisode).mockResolvedValueOnce({ ...episode("old99"), messages: [] });
    renderWithSWR(
      <EpisodesRail roomName="atlas" focusEpisode={{ shortId: "old99", nonce: 1 }} />,
    );

    await waitFor(() => expect(fetchEpisode).toHaveBeenCalledWith("atlas", "old99"));
    expect(await screen.findByTestId("episode-detail")).toHaveTextContent("old99");
  });
});
