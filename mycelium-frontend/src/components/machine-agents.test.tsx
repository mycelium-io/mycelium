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
    kind: "resume",
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

/** The mock machine after a herdr restart: one working, one stopped, one unsynced, one gone. */
function machine() {
  const r = listRunners()[0];
  if (!r.machine) throw new Error("the mock runner reports no machine");
  return r;
}

describe("MachineAgents", () => {
  beforeEach(() => {
    machineAction.mockReset();
    fetchRunnerJob.mockReset();
  });

  it("groups agents by where they run, with their state", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("herdr · checkout")).toBeInTheDocument();
    expect(screen.getByText("Panes that are gone")).toBeInTheDocument();
    const reviewer = screen.getByText("@reviewer").closest("tr") as HTMLElement;
    expect(within(reviewer).getByText("Stopped, pane open")).toBeInTheDocument();
    expect(within(reviewer).getByRole("button", { name: "Resume" })).toBeInTheDocument();
    // A stopped agent has nothing to stop or rename.
    expect(within(reviewer).queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it("shows each problem with its fix from a terminal", () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    expect(screen.getByText("mycelium machine resume --all")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep it synced" })).toBeInTheDocument();
  });

  it("shows what resuming runs, and asks the machine for the ones picked", async () => {
    machineAction.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(job({ status: "waiting" }));
    renderWithSWR(<MachineAgents runner={machine()} />);

    fireEvent.click(screen.getByRole("button", { name: /^Resume 1…/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/claude --resume/)).toBeInTheDocument();
    expect(within(dialog).getByText(/ask once more/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Resume 1" }));
    await waitFor(() =>
      expect(machineAction).toHaveBeenCalledWith("morgans-mbp", {
        kind: "resume",
        agents: [{ handle: "reviewer", room: "checkout" }],
      }),
    );
    expect(await within(dialog).findByText("Waiting for a yes on morgans-mbp.")).toBeInTheDocument();
  });

  it("resumes nobody once every agent is unticked", async () => {
    renderWithSWR(<MachineAgents runner={machine()} />);
    fireEvent.click(screen.getByRole("button", { name: /^Resume 1…/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Resume @reviewer" }));
    expect(within(dialog).getByRole("button", { name: "Resume 0" })).toBeDisabled();
  });

  it("turns a workspace's sync on", async () => {
    machineAction.mockResolvedValue(job({ kind: "sync" }));
    renderWithSWR(<MachineAgents runner={machine()} />);
    fireEvent.click(screen.getByRole("switch", { name: "Keep storefront synced" }));
    await waitFor(() =>
      expect(machineAction).toHaveBeenCalledWith("morgans-mbp", { kind: "sync", workspace: "w5", on: true }),
    );
  });

  it("finds a session but saves it only when told it's the one", async () => {
    machineAction.mockResolvedValueOnce(job({ id: "job-find", kind: "session" }));
    fetchRunnerJob.mockResolvedValue(
      job({
        id: "job-find",
        kind: "session",
        status: "done",
        result: { found: { id: "5d1c2f0e-aaaa-bbbb-cccc-0123456789ab", modified: "2026-10-01T11:00:00Z" } },
      }),
    );
    renderWithSWR(<MachineAgents runner={machine()} />);
    const row = screen.getByText("@copywriter").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "find it" }));
    const confirm = await within(row).findByRole("button", { name: "It's this one" });
    expect(machineAction).toHaveBeenCalledTimes(1);

    machineAction.mockResolvedValueOnce(job({ id: "job-save", kind: "session" }));
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(machineAction).toHaveBeenLastCalledWith("morgans-mbp", {
        kind: "session",
        handle: "copywriter",
        room: "storefront",
        session: "5d1c2f0e-aaaa-bbbb-cccc-0123456789ab",
      }),
    );
  });
});
