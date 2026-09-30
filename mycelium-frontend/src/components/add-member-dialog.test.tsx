import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
const createEngine = vi.fn();
const createMemories = vi.fn();
const registerA2aAgent = vi.fn();
vi.mock("@/lib/api", () => ({
  createEngine: (...a: unknown[]) => createEngine(...a),
  createMemories: (...a: unknown[]) => createMemories(...a),
  registerA2aAgent: (...a: unknown[]) => registerA2aAgent(...a),
  launchRunnerAgent: vi.fn(),
  fetchRunnerJob: vi.fn(),
  rescanRunner: vi.fn(),
}));
vi.mock("@/lib/room-data", () => ({
  useRoomRevalidate: () => vi.fn(),
  useNetworkStatus: () => ({ network: { auth: { enabled: false } } }),
}));
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: [], connected: [], loading: false, refresh: vi.fn() }),
}));

import { AddMemberDialog } from "./add-member-dialog";

function open(kind?: "machine" | "engine" | "a2a" | "session") {
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
  });

  it("offers every kind of member from one place", () => {
    open();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Your machineStarted on your computer",
      "EngineRuns on this hub",
      "A2A serviceRuns elsewhere",
      "Open sessionAlready open",
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

  it("hands an open session the setup to paste", () => {
    const { onOpenChange } = open("session");
    expect(screen.getByText(/You are joining the Mycelium room `atlas`/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
