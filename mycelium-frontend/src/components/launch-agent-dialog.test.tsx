import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const launchRunnerAgent = vi.fn();
const fetchRunnerJob = vi.fn();
vi.mock("@/lib/api", () => ({
  launchRunnerAgent: (...args: unknown[]) => launchRunnerAgent(...args),
  fetchRunnerJob: (...args: unknown[]) => fetchRunnerJob(...args),
  rescanRunner: vi.fn(),
}));
vi.mock("@/lib/room-data", () => ({ useRoomRevalidate: () => vi.fn() }));
let connected: Runner[] = [];
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: connected, connected, loading: false, refresh: vi.fn() }),
}));

import type { Runner, RunnerJob } from "@/lib/api";
import { runner } from "@/lib/runners.fixture";
import { LaunchAgentForm } from "./launch-agent-dialog";

function job(over: Partial<RunnerJob> = {}): RunnerJob {
  return {
    id: "job-0009",
    runner: "julias-mbp",
    kind: "launch",
    spec: {},
    status: "queued",
    result: null,
    error: null,
    created_by: "julia",
    created_at: "2026-09-28T12:00:00Z",
    updated_at: "2026-09-28T12:00:00Z",
    ...over,
  };
}

describe("LaunchAgentForm", () => {
  beforeEach(() => {
    connected = [];
    launchRunnerAgent.mockReset();
    fetchRunnerJob.mockReset();
  });

  it("says how to connect a machine when none is", () => {
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);
    expect(screen.getByText("Connect this machine")).toBeInTheDocument();
    expect(screen.getByDisplayValue("mycelium runner")).toBeInTheDocument();
  });

  it("offers only what the machine can start, leaving the rest of the scan out", () => {
    connected = [runner()];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    const choices = screen.getAllByRole("radio").map((r) => r.getAttribute("aria-label"));
    expect(choices).toEqual(["Claude Code", "opencode"]);
    expect(screen.getByRole("radio", { name: "Claude Code" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(/Codex/)).not.toBeInTheDocument();
  });

  it("registers the agent and starts it, then follows the machine until it runs", async () => {
    connected = [runner()];
    launchRunnerAgent.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(job({ status: "done" }));
    const onLaunched = vi.fn();
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={onLaunched} />);

    fireEvent.click(screen.getByRole("radio", { name: "opencode" }));
    fireEvent.change(screen.getByLabelText(/^Handle/), { target: { value: "@Reviewer" } });
    fireEvent.change(screen.getByLabelText(/Instructions/), {
      target: { value: "  Review every change for correctness.  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start opencode" }));

    await waitFor(() => expect(onLaunched).toHaveBeenCalledWith("reviewer"));
    expect(launchRunnerAgent).toHaveBeenCalledWith("julias-mbp", {
      room: "atlas",
      handle: "reviewer",
      framework: "opencode",
      instructions: "Review every change for correctness.",
      cwd: "/Users/julia/code/atlas",
      created_by: "julia",
    });
    expect(fetchRunnerJob).toHaveBeenCalledWith("julias-mbp", "job-0009");
  });

  it("shows the machine's reason when it could not start the agent", async () => {
    connected = [runner()];
    launchRunnerAgent.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({ status: "failed", error: "/tmp is outside the folders julias-mbp allows." }),
    );
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/^Handle/), { target: { value: "scout" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Claude Code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("outside the folders");
  });

  it("can't start anything on a machine without herdr, and says why", () => {
    connected = [runner({ herdr: false })];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    expect(screen.getByRole("note")).toHaveTextContent(
      "herdr isn't running on julias-mbp. Install it from https://herdr.dev",
    );
    expect(screen.queryAllByRole("radio")).toEqual([]);
    expect(screen.getByText("Nothing can start here until herdr is running.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Handle/), { target: { value: "scout" } });
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });
});
