import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const startSwarm = vi.fn();
vi.mock("@/lib/api", () => ({ startSwarm: (...args: unknown[]) => startSwarm(...args) }));

import { StartSwarmDialog } from "./start-swarm-dialog";

describe("StartSwarmDialog", () => {
  beforeEach(() => {
    push.mockReset();
    startSwarm.mockReset();
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
    expect(startSwarm).toHaveBeenCalledWith({
      task: "Write release notes for the 2.0 launch",
      size: 4,
      room: "launch",
      created_by: "julia",
    });
    expect(push).toHaveBeenCalledWith("/room/launch?focus=episode:5cc0a8c5");
    expect(onClose).toHaveBeenCalled();
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
