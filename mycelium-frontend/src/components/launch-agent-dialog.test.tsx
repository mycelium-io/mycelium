import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const launchRunnerAgent = vi.fn();
const fetchRunnerJob = vi.fn();
const draftMemberNotes = vi.fn();
vi.mock("@/lib/api", () => ({
  launchRunnerAgent: (...args: unknown[]) => launchRunnerAgent(...args),
  draftMemberNotes: (...args: unknown[]) => draftMemberNotes(...args),
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
import { LaunchAgentForm, expandPath, tildePath } from "./launch-agent-dialog";

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
    window.localStorage.clear();
    launchRunnerAgent.mockReset();
    fetchRunnerJob.mockReset();
    draftMemberNotes.mockReset();
  });

  it("says how to connect a machine when none is", () => {
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);
    expect(screen.getByText("Connect this machine")).toBeInTheDocument();
    expect(screen.getByDisplayValue("mycelium runner")).toBeInTheDocument();
  });

  it("offers only the agent CLIs the machine can start", () => {
    connected = [runner()];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    const cli = screen.getByLabelText("Agent CLI");
    expect(within(cli).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Claude Code 2.4.1",
      "opencode 0.9.3",
    ]);
  });

  it("starts from a role, filling the handle until you type one", () => {
    connected = [runner()];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    fireEvent.click(screen.getByRole("radio", { name: "reviewer" }));
    expect(screen.getByLabelText("Handle")).toHaveValue("reviewer");
    expect((screen.getByLabelText("Instructions") as HTMLTextAreaElement).value).toMatch(/review/);

    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "rita" } });
    fireEvent.click(screen.getByRole("radio", { name: "tester" }));
    expect(screen.getByLabelText("Handle")).toHaveValue("rita");

    fireEvent.click(screen.getByRole("radio", { name: "blank" }));
    expect(screen.getByLabelText("Instructions")).toHaveValue("");
  });

  it("keeps instructions you wrote as a role of your own", () => {
    connected = [runner()];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Instructions"), { target: { value: "Triage issues." } });
    fireEvent.click(screen.getByRole("button", { name: "Save as a role" }));
    fireEvent.change(screen.getByLabelText("Role name"), { target: { value: "triager" } });
    fireEvent.submit(screen.getByLabelText("Role name").closest("form")!);

    expect(screen.getByRole("radio", { name: "triager" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: "Delete triager" }));
    expect(screen.queryByRole("radio", { name: "triager" })).not.toBeInTheDocument();
  });

  it("adds the agent, then follows the machine until it runs", async () => {
    connected = [runner()];
    launchRunnerAgent.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(job({ status: "done" }));
    const onLaunched = vi.fn();
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={onLaunched} />);

    fireEvent.change(screen.getByLabelText("Agent CLI"), { target: { value: "opencode" } });
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "@Reviewer" } });
    fireEvent.change(screen.getByLabelText("Instructions"), {
      target: { value: "  Review every change for correctness.  " },
    });
    fireEvent.change(screen.getByLabelText("Folder"), { target: { value: "~/code/atlas/api" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));

    await waitFor(() => expect(onLaunched).toHaveBeenCalledWith("reviewer"));
    expect(launchRunnerAgent).toHaveBeenCalledWith("julias-mbp", {
      room: "atlas",
      handle: "reviewer",
      framework: "opencode",
      instructions: "Review every change for correctness.",
      cwd: "/Users/julia/code/atlas/api",
      created_by: "julia",
    });
    expect(await screen.findByText(/Running on julias-mbp/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add another" })).toBeInTheDocument();
  });

  it("says an agent that started at a prompt is waiting for input on the machine", async () => {
    connected = [runner()];
    launchRunnerAgent.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({
        status: "done",
        result: { pane: "w9:p1", waiting: "waiting for input on julias-mbp\nAnswer it in its pane: herdr agent focus w9:p1" },
      }),
    );
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "reviewer" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));

    expect(await screen.findByText(/waiting for input there/)).toBeInTheDocument();
    expect(screen.getByText(/herdr agent focus w9:p1/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the machine's reason when it could not start the agent", async () => {
    connected = [runner()];
    launchRunnerAgent.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({ status: "failed", error: "/tmp is outside the folders julias-mbp allows." }),
    );
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "scout" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("outside the folders");
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Handle")).toHaveValue("scout");
  });

  it("can't start anything on a machine without herdr, and says why", () => {
    connected = [runner({ herdr: false })];
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    expect(screen.getByRole("note")).toHaveTextContent(
      "herdr isn't running on julias-mbp. Install it from https://herdr.dev",
    );
    expect(screen.queryByLabelText("Agent CLI")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "scout" } });
    expect(screen.getByRole("button", { name: "Add to room" })).toBeDisabled();
  });
});

describe("Expand", () => {
  beforeEach(() => {
    connected = [runner()];
    draftMemberNotes.mockReset();
  });

  it("expands a line into the hub's draft, and Undo puts the line back", async () => {
    draftMemberNotes.mockResolvedValue("You review every pull request in this room.");
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "rev" } });
    const box = screen.getByLabelText("Instructions");
    fireEvent.change(box, { target: { value: "reviews PRs" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    await waitFor(() => expect(box).toHaveValue("You review every pull request in this room."));
    expect(draftMemberNotes).toHaveBeenCalledWith("atlas", { brief: "reviews PRs", handle: "rev", kind: "agent" });

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(box).toHaveValue("reviews PRs");
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("is off with nothing typed, and says so when the hub can't draft", async () => {
    draftMemberNotes.mockRejectedValue(new Error("The hub's model couldn't write a draft. Try again."));
    renderWithSWR(<LaunchAgentForm roomName="atlas" onLaunched={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Expand" })).toBeDisabled();
    const box = screen.getByLabelText("Instructions");
    fireEvent.change(box, { target: { value: "reviews PRs" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't write a draft");
    expect(box).toHaveValue("reviews PRs");
  });
});

describe("folder paths", () => {
  it("shows a home folder as ~ and sends it back expanded", () => {
    expect(tildePath("/Users/julia/code/atlas")).toBe("~/code/atlas");
    expect(tildePath("/home/julia")).toBe("~");
    expect(tildePath("/srv/code")).toBe("/srv/code");
    expect(expandPath("~/code/x", ["/Users/julia/code"])).toBe("/Users/julia/code/x");
    expect(expandPath("/abs/path", ["/Users/julia/code"])).toBe("/abs/path");
  });
});
