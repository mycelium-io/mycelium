import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const startSwarm = vi.fn();
vi.mock("@/lib/api", () => ({ startSwarm: (...args: unknown[]) => startSwarm(...args) }));
let connected: Runner[] = [];
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: connected, connected, loading: false, refresh: vi.fn() }),
}));

import type { Runner } from "@/lib/api";
import { runner } from "@/lib/runners.fixture";
import { StartSwarmDialog } from "./start-swarm-dialog";

describe("StartSwarmDialog", () => {
  beforeEach(() => {
    push.mockReset();
    startSwarm.mockReset();
    connected = [];
  });

  it("puts the team on a connected machine's agent CLI instead of the hub", async () => {
    connected = [runner()];
    startSwarm.mockResolvedValue({
      room: "launch",
      key: "work/fix-the-flaky-tests",
      episode: "urn:ioc:mycelium:episode:launch:9f8e7d6c",
      members: ["agent-1", "agent-2", "agent-3"],
      job: "job-0007",
    });
    render(<StartSwarmDialog open onClose={vi.fn()} roomName="launch" />);

    fireEvent.change(screen.getByLabelText("What should the team work on?"), {
      target: { value: "Fix the flaky tests" },
    });
    fireEvent.click(screen.getByRole("radio", { name: "On julias-mbp" }));
    // The repository is the hub's; a machine's team works in a folder there.
    expect(screen.queryByLabelText(/Repository/)).not.toBeInTheDocument();
    // Only what the machine can start is offered.
    expect(screen.queryByRole("radio", { name: "Codex CLI" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "opencode" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Start swarm" }));

    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(startSwarm).toHaveBeenCalledWith("launch", {
      task: "Fix the flaky tests",
      size: 3,
      created_by: "julia",
      runner: "julias-mbp",
      framework: "opencode",
      cwd: "/Users/julia/code/atlas",
      worktree: true,
    });
  });

  it("can't start on a machine without herdr, and says why", () => {
    connected = [runner({ herdr: false })];
    render(<StartSwarmDialog open onClose={vi.fn()} roomName="launch" initialTask="Anything" />);

    fireEvent.click(screen.getByRole("radio", { name: "On julias-mbp" }));
    expect(screen.getByRole("note")).toHaveTextContent("herdr isn't running on julias-mbp");
    expect(screen.getByRole("button", { name: "Start swarm" })).toBeDisabled();
  });

  it("offers the CLI command only when no machine is connected", () => {
    render(<StartSwarmDialog open onClose={vi.fn()} roomName="launch" />);
    expect(screen.getByText("Or use the agents on your machine")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Where" })).not.toBeInTheDocument();
  });

  it("starts a team on the task in this room and opens the task's thread", async () => {
    startSwarm.mockResolvedValue({
      room: "launch",
      key: "work/write-release-notes",
      episode: "urn:ioc:mycelium:episode:launch:5cc0a8c5",
      members: ["agent-1", "agent-2", "agent-3", "agent-4"],
    });
    const onClose = vi.fn();
    render(<StartSwarmDialog open onClose={onClose} roomName="launch" />);

    const start = screen.getByRole("button", { name: "Start swarm" });
    expect(start).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What should the team work on?"), {
      target: { value: "Write release notes for the 2.0 launch" },
    });
    fireEvent.click(screen.getByRole("radio", { name: "4" }));
    fireEvent.click(start);

    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(startSwarm).toHaveBeenCalledWith("launch", {
      task: "Write release notes for the 2.0 launch",
      size: 4,
      created_by: "julia",
    });
    expect(push).toHaveBeenCalledWith("/room/launch?focus=episode:5cc0a8c5");
    expect(onClose).toHaveBeenCalled();
  });

  it("hands the hub a repository to clone when one is given", async () => {
    startSwarm.mockResolvedValue({
      room: "api",
      key: "work/add-a-health-check",
      episode: "urn:ioc:mycelium:episode:api:1a2b3c4d",
      members: ["agent-1", "agent-2", "agent-3"],
    });
    render(<StartSwarmDialog open onClose={vi.fn()} roomName="api" />);

    fireEvent.change(screen.getByLabelText("What should the team work on?"), {
      target: { value: "Add a health check" },
    });
    fireEvent.change(screen.getByLabelText(/Repository/), {
      target: { value: "  https://github.com/org/api  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start swarm" }));

    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(startSwarm).toHaveBeenCalledWith(
      "api",
      expect.objectContaining({ task: "Add a health check", repo: "https://github.com/org/api" }),
    );
  });

  it("starts from what was typed on the board", () => {
    render(
      <StartSwarmDialog open onClose={vi.fn()} roomName="launch" initialTask="Draft the FAQ" />,
    );
    expect(screen.getByLabelText("What should the team work on?")).toHaveValue("Draft the FAQ");
    expect(screen.getByRole("button", { name: "Start swarm" })).toBeEnabled();
  });

  it("says why when the hub refuses", async () => {
    startSwarm.mockRejectedValue(new Error("this hub doesn't run worker engines yet"));
    render(<StartSwarmDialog open onClose={vi.fn()} roomName="launch" />);

    fireEvent.change(screen.getByLabelText("What should the team work on?"), {
      target: { value: "Anything" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start swarm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("doesn't run worker engines");
    expect(push).not.toHaveBeenCalled();
  });
});
