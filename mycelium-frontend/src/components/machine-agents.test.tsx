import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

const machineAction = vi.fn();
const fetchRunnerJob = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  machineAction: (...args: unknown[]) => machineAction(...args),
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

/** The mock machine after a herdr restart with no integrations installed. */
function machine() {
  const r = listRunners()[0];
  if (!r.machine) throw new Error("the mock runner reports no machine");
  return r;
}

const row = (handle: string) => screen.getByText(`@${handle}`).closest("tr") as HTMLElement;

describe("MachineAgents", () => {
  beforeEach(() => {
    machineAction.mockReset();
    fetchRunnerJob.mockReset();
  });

  it("groups agents by where they run, with their state and what a herdr restart does to them", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("herdr · checkout")).toBeInTheDocument();
    expect(screen.getByText("Panes that are gone")).toBeInTheDocument();
    const reviewer = row("reviewer");
    expect(within(reviewer).getByText("Stopped, pane open")).toBeInTheDocument();
    expect(within(reviewer).getByText("Stops")).toBeInTheDocument();
    expect(within(reviewer).getByRole("button", { name: "Restart" })).toBeInTheDocument();
    // A stopped agent has nothing to stop or rename.
    expect(within(reviewer).queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it("restarts any agent CLI the same way", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    const scribe = row("scribe");
    expect(within(scribe).getByText("storefront · opencode")).toBeInTheDocument();
    expect(within(scribe).getByRole("button", { name: "Restart" })).toBeInTheDocument();
  });

  it("shows each problem with its fix from a terminal", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("mycelium machine restart --all")).toBeInTheDocument();
    expect(screen.getByText("mycelium machine integrations --install")).toBeInTheDocument();
    expect(screen.getByText(/Mycelium needs 0\.9\.3 or newer/)).toBeInTheDocument();
    // The runner syncs every bound workspace; there's nothing to switch on.
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("says what restarting does, and asks the machine for the ones picked", async () => {
    machineAction.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(job({ status: "waiting" }));
    renderWithSWR(<MachineAgents runner={machine()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Restart 2…/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/catches up from the room/)).toBeInTheDocument();
    expect(within(dialog).getByText(/ask once more/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Restart @scribe" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Restart 1" }));
    await waitFor(() =>
      expect(machineAction).toHaveBeenCalledWith("morgans-mbp", {
        kind: "restart",
        agents: [{ handle: "reviewer", room: "checkout" }],
      }),
    );
    expect(await within(dialog).findByText("Waiting for a yes on morgans-mbp.")).toBeInTheDocument();
  });

  it("restarts nobody once every agent is unticked", async () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    fireEvent.click(screen.getByRole("button", { name: /^Restart 2…/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Restart @reviewer" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Restart @scribe" }));
    expect(within(dialog).getByRole("button", { name: "Restart 0" })).toBeDisabled();
  });

  it("asks the machine to install herdr's integrations", async () => {
    machineAction.mockResolvedValue(job({ kind: "integrations" }));
    renderWithSWR(<MachineAgents runner={machine()} />);
    fireEvent.click(screen.getByRole("button", { name: "Install integrations" }));
    await waitFor(() => expect(machineAction).toHaveBeenCalledWith("morgans-mbp", { kind: "integrations" }));
  });
});
