// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UnregisterAgentDialog } from "@/components/unregister-agent-dialog";
import { deleteMemory, stopRunnerAgent } from "@/lib/api";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  deleteMemory: vi.fn(),
  stopRunnerAgent: vi.fn(),
}));

describe("<UnregisterAgentDialog />", () => {
  beforeEach(() => {
    vi.mocked(deleteMemory).mockReset().mockResolvedValue(undefined);
    vi.mocked(stopRunnerAgent).mockReset();
  });

  it("deletes the agent's manifest, leaving its notes", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onUnregistered = vi.fn();
    renderWithSWR(
      <UnregisterAgentDialog
        roomName="checkout"
        target={{ handle: "builder" }}
        onClose={onClose}
        onUnregistered={onUnregistered}
      />,
    );

    expect(screen.queryByRole("checkbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Unregister" }));

    expect(deleteMemory).toHaveBeenCalledWith("checkout", "agents/builder");
    expect(stopRunnerAgent).not.toHaveBeenCalled();
    expect(onUnregistered).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("stops an agent your machine started, unless told not to", async () => {
    const user = userEvent.setup();
    const target = { handle: "builder", runner: { id: "r1", name: "laptop" } };
    const { unmount } = renderWithSWR(
      <UnregisterAgentDialog roomName="checkout" target={target} onClose={vi.fn()} onUnregistered={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: "Unregister" }));
    expect(stopRunnerAgent).toHaveBeenCalledWith("r1", "checkout", "builder");
    unmount();

    vi.mocked(stopRunnerAgent).mockClear();
    renderWithSWR(
      <UnregisterAgentDialog roomName="checkout" target={target} onClose={vi.fn()} onUnregistered={vi.fn()} />,
    );
    await user.click(screen.getByText("Also stop it on laptop"));
    await user.click(screen.getByRole("button", { name: "Unregister" }));
    expect(stopRunnerAgent).not.toHaveBeenCalled();
    expect(deleteMemory).toHaveBeenCalledTimes(2);
  });

  it("keeps the dialog open and the agent registered when the delete fails", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    vi.mocked(deleteMemory).mockRejectedValue(new Error("Memory not found"));
    renderWithSWR(
      <UnregisterAgentDialog
        roomName="checkout"
        target={{ handle: "builder" }}
        onClose={onClose}
        onUnregistered={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Unregister" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Memory not found");
    expect(onClose).not.toHaveBeenCalled();
  });
});
