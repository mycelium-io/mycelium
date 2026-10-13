import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const createEngine = vi.fn();
const createMemories = vi.fn();
const registerA2aAgent = vi.fn();
const adoptRunnerAgent = vi.fn();
vi.mock("@/lib/api", () => ({
  adoptRunnerAgent: (...a: unknown[]) => adoptRunnerAgent(...a),
  createEngine: (...a: unknown[]) => createEngine(...a),
  createMemories: (...a: unknown[]) => createMemories(...a),
  registerA2aAgent: (...a: unknown[]) => registerA2aAgent(...a),
  launchRunnerAgent: vi.fn(),
  draftMemberNotes: vi.fn(),
  fetchRunnerJob: vi.fn(),
  rescanRunner: vi.fn(),
}));
vi.mock("@/lib/room-data", () => ({
  useRoomRevalidate: () => vi.fn(),
  useNetworkStatus: () => ({ network: { auth: { enabled: false } } }),
}));
let machines: Runner[] = [];
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: machines, connected: machines, loading: false, refresh: vi.fn() }),
}));

import type { MachineUnenrolled, Runner } from "@/lib/api";
import { AddMemberDialog, type MemberKind } from "./add-member-dialog";

function running(pane: string, over: Partial<MachineUnenrolled> = {}): MachineUnenrolled {
  return {
    pane,
    kind: "claude",
    state: "idle",
    folder: "/Users/julia/code/shop",
    workspace: "w5",
    workspace_label: "shop",
    tab_label: "Checkout Fix",
    suggested_handle: "checkout-fix",
    ...over,
  };
}

/** A laptop with one agent already in atlas (w1:p1) and two in no room. */
function laptop(): Runner {
  return {
    id: "r1",
    label: "julia-mbp",
    owner: "julia",
    platform: "darwin",
    version: "1",
    herdr: true,
    roots: ["/Users/julia/code"],
    frameworks: [{ id: "claude", name: "Claude Code", installed: true, launchable: true } as Runner["frameworks"][number]],
    agents: [
      {
        handle: "scout",
        room: "atlas",
        framework: "claude",
        status: "idle",
        pane: "w1:p1",
        cwd: null,
        started_at: "",
        detail: null,
      },
    ],
    machine: {
      machine: "julia-mbp",
      herdr: true,
      herdr_server: null,
      herdr_client: null,
      herdr_minimum: null,
      runner: true,
      missing_integrations: [],
      workspaces: [],
      problems: [],
      // A heartbeat behind: w1:p1 is in atlas already but still reported here.
      unenrolled: [running("w1:p1"), running("w5:p2"), running("w5:p3", { tab_label: "3", suggested_handle: "codex", kind: "codex" })],
    },
    connected: true,
    last_seen: "",
    started_at: "",
  };
}

function open(kind?: MemberKind) {
  const onAdded = vi.fn();
  const onOpenChange = vi.fn();
  renderWithSWR(
    <AddMemberDialog
      open
      onOpenChange={onOpenChange}
      roomName="atlas"
      initialKind={kind}
      onAdded={onAdded}
    />,
  );
  return { onAdded, onOpenChange };
}

describe("AddMemberDialog", () => {
  beforeEach(() => {
    createEngine.mockReset().mockResolvedValue({});
    createMemories.mockReset().mockResolvedValue(undefined);
    registerA2aAgent.mockReset().mockResolvedValue({});
    adoptRunnerAgent.mockReset().mockResolvedValue({ id: "j1", status: "queued" });
    machines = [];
  });

  it("offers every kind of member from one place", () => {
    open();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Your machineStart a new one",
      "Running agentAlready running",
      "EngineRuns on this hub",
      "A2A serviceRuns elsewhere",
      "Open sessionPaste a prompt",
    ]);
    // No machine connected: the machine kind says how to connect one.
    expect(screen.getByText("Connect this machine")).toBeInTheDocument();
  });

  it("adds an engine named after what it does until you name it", async () => {
    const { onAdded } = open("engine");
    fireEvent.click(screen.getByRole("radio", { name: "synthesizer" }));
    expect(screen.getByLabelText("Handle")).toHaveValue("synthesizer");
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith("synthesizer"));
    expect(createEngine).toHaveBeenCalledWith("atlas", {
      handle: "synthesizer",
      kind: "synthesizer",
      description: "",
      created_by: "julia",
    });
    expect(createMemories).not.toHaveBeenCalled();
  });

  it("gives a persona its character as notes", async () => {
    const { onAdded } = open("engine");
    fireEvent.click(screen.getByRole("radio", { name: "persona" }));
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "skeptic" } });
    fireEvent.change(screen.getByLabelText("Instructions"), {
      target: { value: "You doubt every estimate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith("skeptic"));
    expect(createMemories).toHaveBeenCalledWith("atlas", [
      { key: "agents/skeptic/notes", value: "You doubt every estimate.", created_by: "julia" },
    ]);
  });

  it("shows why the hub refused, and adds nothing more", async () => {
    createEngine.mockRejectedValue(new Error("@aligner already exists in atlas"));
    const { onAdded } = open("engine");
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    expect(onAdded).not.toHaveBeenCalled();
  });

  it("connects an A2A service by its card", async () => {
    const { onAdded } = open("a2a");
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "@Accounts" } });
    const connect = screen.getByRole("button", { name: "Connect @accounts" });
    expect(connect).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Agent card URL"), {
      target: { value: " https://accounts.example.com " },
    });
    fireEvent.click(connect);

    await waitFor(() => expect(onAdded).toHaveBeenCalledWith("accounts"));
    expect(registerA2aAgent).toHaveBeenCalledWith("atlas", {
      handle: "accounts",
      card: "https://accounts.example.com",
      description: "",
    });
  });

  it("lists only the running agents no room has", () => {
    machines = [laptop()];
    open("running");
    const listed = screen.getAllByRole("radio").map((r) => r.textContent);
    expect(listed).toHaveLength(2);
    expect(listed[0]).toContain("Claude Code");
    expect(listed[0]).toContain("Checkout Fix · ~/code/shop");
    expect(listed[1]).toContain("codex");
    // The first is picked, and its handle comes from its tab name.
    expect(screen.getByLabelText("Handle")).toHaveValue("checkout-fix");
    fireEvent.click(screen.getAllByRole("radio")[1]);
    expect(screen.getByLabelText("Handle")).toHaveValue("codex");
  });

  it("brings the picked agent in under the handle you give it", async () => {
    machines = [laptop()];
    open("running");
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "@Shop" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to room" }));
    await waitFor(() =>
      expect(adoptRunnerAgent).toHaveBeenCalledWith("r1", {
        room: "atlas",
        pane: "w5:p2",
        handle: "shop",
        created_by: "julia",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Sent to julia-mbp.");
  });

  it("says so when every running agent is in a room", () => {
    const machine = laptop();
    machine.machine!.unenrolled = [running("w1:p1")];
    machines = [machine];
    open("running");
    expect(screen.queryAllByRole("radio")).toEqual([]);
    expect(screen.getByText("Every agent running on julia-mbp is in a room already.")).toBeInTheDocument();
  });

  it("hands an open session the setup to paste", () => {
    const { onOpenChange } = open("session");
    expect(screen.getByText(/You are joining the Mycelium room `atlas`/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
