// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RenameAgentDialog } from "@/components/rename-agent-dialog";
import { renameAgent, type AgentRenamed } from "@/lib/api";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  renameAgent: vi.fn(),
}));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal: "julia" }),
}));
/** The restart job as the machine last reported it. */
const job = { status: "waiting", error: null as string | null, spec: {} as Record<string, unknown> };
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: [{ id: "mbp", label: "morgans-mbp" }], connected: [], loading: false }),
  useRunnerJob: (runner: string | null) => ({ job: runner ? { ...job } : undefined }),
}));

/** What the hub answers for an agent a machine runs: nothing changed yet. */
function waiting(over: Partial<AgentRenamed> = {}): AgentRenamed {
  return {
    handle: "docs-writer",
    was: "voice-model",
    pending: true,
    memories: [],
    rows: [],
    restart_runner: "mbp",
    restart_job: "j1",
    ...over,
  };
}

function open(onRenamed = vi.fn(), onClose = vi.fn()) {
  renderWithSWR(
    <RenameAgentDialog roomName="checkout" handle="voice-model" onClose={onClose} onRenamed={onRenamed} />,
  );
  return { onRenamed, onClose };
}

async function renameTo(name: string) {
  const user = userEvent.setup();
  const field = screen.getByLabelText("Handle");
  await user.clear(field);
  await user.type(field, name);
  await user.click(screen.getByRole("button", { name: "Rename" }));
  return user;
}

describe("<RenameAgentDialog />", () => {
  beforeEach(() => {
    vi.mocked(renameAgent).mockReset();
    Object.assign(job, { status: "waiting", error: null, spec: {} });
  });

  it("asks the machine running it, and changes nothing until it's approved", async () => {
    vi.mocked(renameAgent).mockImplementation(async () => waiting());
    const { onRenamed, onClose } = open();

    // Starts at its current name, which isn't a rename yet.
    expect(screen.getByLabelText("Handle")).toHaveValue("voice-model");
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();

    const user = await renameTo("Docs-Writer");
    expect(renameAgent).toHaveBeenCalledWith("checkout", "voice-model", "docs-writer", "julia");
    expect(await screen.findByText("Rename @voice-model")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waiting for approval on morgans-mbp. Nothing changes until then.",
    );
    expect(onRenamed).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("says renamed once the machine approved and restarted it", async () => {
    Object.assign(job, { status: "done", spec: { applied: true } });
    vi.mocked(renameAgent).mockImplementation(async () => waiting());
    const { onRenamed } = open();
    await renameTo("docs-writer");
    expect(await screen.findByText("Renamed to @docs-writer")).toBeInTheDocument();
    expect(screen.getByText("We let checkout know.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Restarted on morgans-mbp.");
    expect(onRenamed).toHaveBeenCalledWith("docs-writer");
  });

  it("says not renamed when the machine said no", async () => {
    Object.assign(job, { status: "failed", error: "Declined on morgans-mbp." });
    vi.mocked(renameAgent).mockImplementation(async () => waiting());
    const { onRenamed } = open();
    await renameTo("docs-writer");
    expect(await screen.findByText("Not renamed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Declined on morgans-mbp. @voice-model is unchanged.");
    expect(onRenamed).not.toHaveBeenCalled();
  });

  it("says when it was renamed but couldn't restart", async () => {
    Object.assign(job, { status: "failed", error: "herdr couldn't end @voice-model", spec: { applied: true } });
    vi.mocked(renameAgent).mockImplementation(async () => waiting());
    open();
    await renameTo("docs-writer");
    expect(await screen.findByText("Renamed to @docs-writer")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't restart on morgans-mbp: herdr couldn't end @voice-model. Restart it with the new name.",
    );
  });

  it("renames at once when no machine runs it", async () => {
    vi.mocked(renameAgent).mockImplementation(async () =>
      waiting({ pending: false, rows: ["work/a"], restart_runner: null, restart_job: null }),
    );
    const { onRenamed } = open();
    await renameTo("docs-writer");
    expect(await screen.findByText("Renamed to @docs-writer")).toBeInTheDocument();
    expect(screen.getByText("We let checkout know. 1 task moved with it.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "It isn't running on any of your machines. Restart it with the new name to use it.",
    );
    expect(onRenamed).toHaveBeenCalledWith("docs-writer");
  });

  it("shows why the hub refused and stays open", async () => {
    vi.mocked(renameAgent).mockImplementation(async () => {
      throw new Error("@hay is already a member of checkout.");
    });
    const { onClose } = open();
    await renameTo("hay");
    expect(await screen.findByRole("alert")).toHaveTextContent("@hay is already a member of checkout.");
    expect(onClose).not.toHaveBeenCalled();
  });
});
