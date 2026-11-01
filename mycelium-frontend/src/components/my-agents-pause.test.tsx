import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

const fetchMyPaused = vi.fn();
const controlMyAgents = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchMyPaused: (...args: unknown[]) => fetchMyPaused(...args),
  controlMyAgents: (...args: unknown[]) => controlMyAgents(...args),
}));

import { CurrentUserProvider } from "@/components/current-user";
import { KeymapProvider } from "@/components/keymap-provider";
import { MyAgentsPause } from "./my-agents-pause";

const PAUSED = [
  { room: "eng", handle: "builder", by: "julia", at: "2026-10-18T23:00:00Z" },
  { room: "docs", handle: "design", by: "julia", at: "2026-10-18T23:00:00Z" },
];

function renderCell() {
  return renderWithSWR(
    <CurrentUserProvider>
      <KeymapProvider>
        <MyAgentsPause />
      </KeymapProvider>
    </CurrentUserProvider>,
  );
}

describe("the status rail's paused cell", () => {
  beforeEach(() => {
    window.localStorage.setItem("mycelium.principal", "julia");
    fetchMyPaused.mockReset();
    controlMyAgents.mockReset().mockResolvedValue({ agents: [] });
  });

  it("says nothing while none of your agents are paused", async () => {
    fetchMyPaused.mockResolvedValue([]);
    renderCell();
    await waitFor(() => expect(fetchMyPaused).toHaveBeenCalledWith("julia"));
    expect(screen.queryByText(/paused/)).toBeNull();
  });

  it("counts your paused agents and resumes them all on a click", async () => {
    fetchMyPaused.mockResolvedValue(PAUSED);
    renderCell();
    fireEvent.click(await screen.findByRole("button", { name: /2 paused/ }));
    await waitFor(() => expect(controlMyAgents).toHaveBeenCalledWith("resume", "julia"));
  });
});
