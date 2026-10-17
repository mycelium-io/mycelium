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
const jobStatus = { status: "waiting" as string, error: null as string | null };
vi.mock("@/lib/runners", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/runners")>()),
  useRunners: () => ({ runners: [{ id: "mbp", label: "morgans-mbp" }], connected: [], loading: false }),
  useRunnerJob: (runner: string | null) => ({ job: runner ? { ...jobStatus } : undefined }),
}));

function renamed(over: Partial<AgentRenamed> = {}): AgentRenamed {
  return {
    handle: "docs-writer",
    was: "voice-model",
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
    jobStatus.status = "waiting";
    jobStatus.error = null;
  });

  it("renames the agent as the person using the app and follows its restart", async () => {
    vi.mocked(renameAgent).mockImplementation(async () => renamed({ rows: ["work/a"] }));
    const { onRenamed, onClose } = open();

    // Starts at its current name, which isn't a rename yet.
    expect(screen.getByLabelText("Handle")).toHaveValue("voice-model");
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();

    const user = await renameTo("Docs-Writer");
    expect(renameAgent).toHaveBeenCalledWith("checkout", "voice-model", "docs-writer", "julia");
    expect(onRenamed).toHaveBeenCalledWith("docs-writer");
    expect(await screen.findByText("@voice-model is @docs-writer")).toBeInTheDocument();
    expect(screen.getByText(/1 task now names it/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waiting for someone on morgans-mbp to approve restarting it as @docs-writer.",
    );

    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("says to restart it by hand when no machine has it", async () => {
    vi.mocked(renameAgent).mockImplementation(async () => renamed({ restart_runner: null, restart_job: null }));
    open();
    await renameTo("docs-writer");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "No connected machine is running it, so restart it yourself with its new name",
    );
  });

  it("says why the machine couldn't restart it", async () => {
    jobStatus.status = "failed";
    jobStatus.error = "Declined on morgans-mbp.";
    vi.mocked(renameAgent).mockImplementation(async () => renamed());
    open();
    await renameTo("docs-writer");
    expect(await screen.findByRole("alert")).toHaveTextContent("morgans-mbp couldn't restart it: Declined on morgans-mbp.");
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
