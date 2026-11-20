// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A task's memory page leads with its title, where it stands and who holds
// it, and the board's verbs a person can use from there.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardRead, Memory } from "@/lib/api";

let board: BoardRead = { epics: [], tasks: [] };
const revalidate = vi.fn();
vi.mock("@/lib/room-data", () => ({
  useRoomBoard: () => ({ board, loading: false, refresh: vi.fn() }),
  useRoomRoster: () => ({ agents: [{ handle: "builder", adapter: "claude_code" }] }),
  useRoomRevalidate: () => revalidate,
}));
const writeAssignment = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  writeAssignment: (...args: unknown[]) => writeAssignment(...args),
}));
vi.mock("@/components/agent-card", () => ({
  AgentCardHover: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { CurrentUserProvider } from "@/components/current-user";
import { TaskHeader } from "./task-header";

const memory = (over: Partial<Memory> = {}): Memory => ({
  key: "work/add-apple-pay",
  value: "Add Apple Pay to checkout\n\nBehind a switch first.",
  version: 2,
  created_by: "julia",
  updated_at: "2026-11-19T12:00:00Z",
  ...over,
});

const part = (over: Partial<BoardRead["tasks"][number]> = {}): BoardRead["tasks"][number] => ({
  key: "work/add-apple-pay",
  title: "Add Apple Pay to checkout",
  state: "working",
  holder: "builder",
  waiting_on: [],
  parts: 0,
  parts_done: 0,
  ...over,
});

function show(m: Memory = memory()) {
  return render(
    <CurrentUserProvider>
      <TaskHeader roomName="checkout" memory={m} />
    </CurrentUserProvider>,
  );
}

describe("TaskHeader", () => {
  beforeEach(() => {
    board = { epics: [], tasks: [] };
    writeAssignment.mockReset().mockResolvedValue({});
    revalidate.mockReset();
    window.localStorage.setItem("mycelium.principal", "julia");
  });

  it("leads with the title, its state and who holds it", () => {
    board = { epics: [], tasks: [part()] };
    show();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Add Apple Pay to checkout");
    expect(screen.getByText("Working")).toBeInTheDocument();
    expect(screen.getByText("Held by @builder")).toBeInTheDocument();
    // Someone else holds it, so there's nothing to claim or release.
    expect(screen.queryByRole("button", { name: /Claim|Release/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it("offers Claim when nobody holds it, and claims it as you", async () => {
    board = { epics: [], tasks: [part({ holder: null, state: "open" })] };
    show();
    expect(screen.getByText("Nobody holds it")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Claim" }));
    await waitFor(() =>
      expect(writeAssignment).toHaveBeenCalledWith("checkout", "claim", { key: "work/add-apple-pay", handle: "julia" }),
    );
    expect(revalidate).toHaveBeenCalled();
  });

  it("offers Release on a task you hold", () => {
    board = { epics: [], tasks: [part({ holder: "@julia" })] };
    show();
    expect(screen.getByText("Held by you")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    expect(writeAssignment).toHaveBeenCalledWith("checkout", "release", { key: "work/add-apple-pay", handle: "julia" });
  });

  it("names the epic a part belongs to", () => {
    board = {
      epics: [
        { ...part({ key: "work/apple-pay", title: "Apple Pay for everyone" }), done: 1, total: 3, steps: [], path: [part()] },
      ],
      tasks: [],
    };
    show();
    expect(screen.getByText("Part of Apple Pay for everyone")).toBeInTheDocument();
  });

  it("reads a task off the board as done, with no actions", () => {
    show(memory({ meta: { assignment: "resolved" } }));
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says when the hub refuses", async () => {
    board = { epics: [], tasks: [part()] };
    writeAssignment.mockRejectedValue(new Error("work/add-apple-pay is held by @builder"));
    show();
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("held by @builder");
  });
});
