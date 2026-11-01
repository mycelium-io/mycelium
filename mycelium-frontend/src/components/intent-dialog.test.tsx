// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

const createTask = vi.fn().mockResolvedValue({ key: "work/fix-the-flaky-login-test", episode: "urn:e:t1" });
const sendRoomMessage = vi.fn().mockResolvedValue(undefined);

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  logFetchError: () => () => undefined,
  createTask: (...args: unknown[]) => createTask(...args),
  sendRoomMessage: (...args: unknown[]) => sendRoomMessage(...args),
  fetchRoomAgents: vi.fn().mockResolvedValue([]),
  fetchRoomMembers: vi.fn().mockResolvedValue({ members: [], floors: [] }),
  fetchMessages: vi.fn().mockResolvedValue({ messages: [] }),
  fetchUsers: async () => [],
}));

vi.mock("@/components/current-user", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/current-user")>()),
  useCurrentUser: () => ({ principal: "julia" }),
  usePrincipal: () => "julia",
}));

import { IntentDialog } from "@/components/intent-dialog";

beforeEach(() => {
  createTask.mockClear();
  sendRoomMessage.mockClear();
});

describe("<IntentDialog /> filing a plain task", () => {
  it("files the details as the task's body, not as a message in its thread", async () => {
    const user = userEvent.setup();
    renderWithSWR(<IntentDialog roomName="demo" initial="task" onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/Fix the flaky login test/), "Fix the flaky login test");
    await user.type(screen.getByRole("textbox", { name: /Details/ }), "It fails one run in five on CI.");
    await user.click(screen.getByRole("button", { name: "File it" }));

    await waitFor(() => expect(createTask).toHaveBeenCalled());
    expect(createTask.mock.calls[0][1]).toMatchObject({
      title: "Fix the flaky login test",
      content: "It fails one run in five on CI.",
      handle: "julia",
    });
    expect(sendRoomMessage).not.toHaveBeenCalled();
  });

  it("files a task with no details as its title alone", async () => {
    const user = userEvent.setup();
    renderWithSWR(<IntentDialog roomName="demo" initial="task" onClose={() => {}} />);
    await user.type(screen.getByPlaceholderText(/Fix the flaky login test/), "Rotate the key");
    await user.click(screen.getByRole("button", { name: "File it" }));

    await waitFor(() => expect(createTask).toHaveBeenCalled());
    expect(createTask.mock.calls[0][1]).not.toHaveProperty("content");
    expect(sendRoomMessage).not.toHaveBeenCalled();
  });
});
