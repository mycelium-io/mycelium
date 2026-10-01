import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

const restartMachineAgents = vi.fn();
const fetchRunnerJob = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  restartMachineAgents: (...args: unknown[]) => restartMachineAgents(...args),
  fetchRunnerJob: (...args: unknown[]) => fetchRunnerJob(...args),
}));

import type { RunnerJob } from "@/lib/api";
import { listRunners } from "@/mocks/runners";
import { MachineAgents } from "./machine-agents";

function job(over: Partial<RunnerJob> = {}): RunnerJob {
  return {
    id: "job-0042",
    runner: "morgans-mbp",
    kind: "restart",
    spec: {},
    status: "queued",
    result: null,
    error: null,
    created_by: "morgan",
    created_at: "2026-10-01T12:00:00Z",
    updated_at: "2026-10-01T12:00:00Z",
    ...over,
  };
}

/** The mock machine the morning after herdr restarted without its integrations. */
function machine() {
  const r = listRunners()[0];
  if (!r.machine) throw new Error("the mock runner reports no machine");
  return r;
}

const row = (handle: string) => screen.getByText(`@${handle}`).closest("tr") as HTMLElement;

describe("MachineAgents", () => {
  beforeEach(() => {
    restartMachineAgents.mockReset();
    fetchRunnerJob.mockReset();
  });

  it("lists each agent with its state and what a herdr restart does to it", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("Panes that are gone")).toBeInTheDocument();
    const reviewer = row("reviewer");
    expect(within(reviewer).getByText("Stopped, pane open")).toBeInTheDocument();
    expect(within(reviewer).getByText("Stops")).toBeInTheDocument();
    expect(within(reviewer).getByRole("button", { name: "Restart" })).toBeInTheDocument();
    // Running, so nothing to restart.
    expect(within(row("builder")).queryByRole("button", { name: "Restart" })).toBeNull();
    // Any agent CLI restarts the same way.
    expect(within(row("scribe")).getByText("storefront · opencode")).toBeInTheDocument();
  });

  it("shows each problem with the command that fixes it", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("mycelium machine restart --all")).toBeInTheDocument();
    expect(screen.getByText("mycelium machine integrations --install")).toBeInTheDocument();
    expect(screen.getByText("mycelium machine unbind --gone")).toBeInTheDocument();
    expect(screen.getByText(/Mycelium needs 0\.9\.3 or newer/)).toBeInTheDocument();
    // Restart is the one fix the page runs; the rest are commands to copy.
    expect(screen.getAllByRole("button").map((b) => b.textContent)).not.toContain("Install integrations");
  });

  it("says what restarting does, and asks the machine for the ones picked", async () => {
    restartMachineAgents.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(job({ status: "waiting" }));
    renderWithSWR(<MachineAgents runner={machine()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Restart 2…/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/catches up from the room/)).toBeInTheDocument();
    expect(within(dialog).getByText(/ask once more/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Restart @scribe" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Restart 1" }));
    await waitFor(() =>
      expect(restartMachineAgents).toHaveBeenCalledWith("morgans-mbp", [{ handle: "reviewer", room: "checkout" }]),
    );
    expect(await within(dialog).findByText("Waiting for a yes on morgans-mbp.")).toBeInTheDocument();
  });

  it("restarts nobody once every agent is unticked", async () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    fireEvent.click(within(row("reviewer")).getByRole("button", { name: "Restart" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Restart @reviewer" }));
    expect(within(dialog).getByRole("button", { name: "Restart 0" })).toBeDisabled();
  });
});
