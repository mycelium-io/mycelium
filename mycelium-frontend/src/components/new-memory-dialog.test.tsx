// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The live-preview editor is CodeMirror; a textarea stands in for it here.
vi.mock("@fedoup/markdown-editor", async () => {
  const { forwardRef, useImperativeHandle, useRef } = await import("react");
  return {
    MarkdownEditor: forwardRef(function MockMdEditor(
      { onChange, placeholder }: { onChange?: (v: string) => void; placeholder?: string },
      ref: import("react").ForwardedRef<{ getValue: () => string; focus: () => void }>,
    ) {
      const el = useRef<HTMLTextAreaElement>(null);
      useImperativeHandle(ref, () => ({
        getValue: () => el.current?.value ?? "",
        focus: () => el.current?.focus(),
      }));
      return <textarea ref={el} aria-label="Body" placeholder={placeholder} onChange={(e) => onChange?.(e.target.value)} />;
    }),
  };
});

const createMemories = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  createMemories: (...a: unknown[]) => createMemories(...a),
}));

const revalidate = vi.fn();
vi.mock("@/lib/room-data", () => ({
  useRoomMemories: () => ({
    memories: [
      { key: "decisions/db", value: "", version: 4, created_by: "sam", updated_at: "" },
      { key: "decisions/cache", value: "", version: 1, created_by: "sam", updated_at: "" },
      { key: "context/goals", value: "", version: 1, created_by: "sam", updated_at: "" },
    ],
    loading: false,
  }),
  useRoomRevalidate: () => revalidate,
}));

vi.mock("@/components/current-user", () => ({
  usePrincipal: () => "julia",
}));

import { NewMemoryDialog } from "@/components/new-memory-dialog";

function open(props: Partial<React.ComponentProps<typeof NewMemoryDialog>> = {}) {
  const onCreated = vi.fn();
  const onOpenChange = vi.fn();
  render(<NewMemoryDialog open onOpenChange={onOpenChange} roomName="atlas" onCreated={onCreated} {...props} />);
  return { onCreated, onOpenChange };
}

describe("<NewMemoryDialog />", () => {
  beforeEach(() => {
    createMemories.mockReset().mockResolvedValue(undefined);
    revalidate.mockReset();
    localStorage.clear();
  });

  it("goes full screen, and Esc there leaves full screen rather than closing", async () => {
    const { onOpenChange } = open();
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).not.toContain("h-dvh");

    await userEvent.click(screen.getByRole("button", { name: "Full screen" }));
    expect(dialog.className).toContain("h-dvh");

    await userEvent.keyboard("{Escape}");
    expect(dialog.className).not.toContain("h-dvh");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("marks it embeddable when asked", async () => {
    open();
    await userEvent.type(screen.getByLabelText("Title"), "Glossary");
    await userEvent.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save memory" }));
    await waitFor(() => expect(createMemories).toHaveBeenCalled());
    expect(createMemories.mock.calls[0][1][0]).toMatchObject({ meta: { expandable: true } });
  });

  it("saves on ⌘S as well as ⌘↵", async () => {
    open();
    await userEvent.type(screen.getByLabelText("Title"), "Quick note");
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    await waitFor(() => expect(createMemories).toHaveBeenCalledOnce());
  });

  it("offers back what was written when it was closed without saving", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const first = render(<NewMemoryDialog open onOpenChange={vi.fn()} roomName="atlas" />);
    try {
      fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Retry policy" } });
      fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Back off exponentially." } });
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
    } finally {
      vi.useRealTimers();
    }
    first.unmount();

    open();
    expect(screen.getByText(/You left unsaved changes here/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Retry policy");
    expect(screen.getByLabelText("Name")).toHaveValue("retry-policy");
  });

  it("keeps nothing after Cancel", async () => {
    open();
    await userEvent.type(screen.getByLabelText("Title"), "Throwaway");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(localStorage.length).toBe(0);
  });

  it("names the memory from its title and shows where it will sit", async () => {
    open({ initialFolder: "decisions" });
    await userEvent.type(screen.getByLabelText("Title"), "Use a queue for retries");

    expect(screen.getByLabelText("Name")).toHaveValue("use-a-queue-for-retries");
    // The new memory sits among the folder's own, marked new.
    expect(screen.getByText("use-a-queue-for-retries")).toBeInTheDocument();
    expect(screen.getByText("new")).toBeInTheDocument();
    expect(screen.getByText("cache")).toBeInTheDocument();
    expect(screen.getByText("db")).toBeInTheDocument();
  });

  it("writes the title as the memory's heading and opens it", async () => {
    const { onCreated, onOpenChange } = open({ initialFolder: "context" });
    await userEvent.type(screen.getByLabelText("Title"), "Launch checklist");
    await userEvent.type(screen.getByLabelText("Body"), "Ship it on Tuesday.");
    await userEvent.click(screen.getByRole("button", { name: "Save memory" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("context/launch-checklist"));
    expect(createMemories).toHaveBeenCalledWith("atlas", [
      expect.objectContaining({
        key: "context/launch-checklist",
        value: "# Launch checklist\n\nShip it on Tuesday.",
        created_by: "julia",
      }),
    ]);
    expect(createMemories.mock.calls[0][1][0]).not.toHaveProperty("base_version");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(revalidate).toHaveBeenCalled();
  });

  it("warns before replacing a memory that already has the name", async () => {
    open({ initialFolder: "decisions" });
    await userEvent.type(screen.getByLabelText("Title"), "DB");

    expect(screen.getByText("replaces v4")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Replace decisions/db" }));
    await waitFor(() => expect(createMemories).toHaveBeenCalled());
    // Only the version the dialog saw, so a concurrent edit isn't overwritten.
    expect(createMemories.mock.calls[0][1][0]).toMatchObject({ base_version: 4 });
  });

  it("marks a folder it would create, and says when a folder files work on the board", async () => {
    open({ initialFolder: "work/infra" });
    await userEvent.type(screen.getByLabelText("Title"), "Retry budget");

    // Neither work/ nor work/infra/ exists yet.
    expect(screen.getAllByText("new folder")).toHaveLength(2);
    expect(screen.getByText(/show up on the board/)).toBeInTheDocument();
  });

  it("refuses a name a key can't hold", async () => {
    open();
    await userEvent.type(screen.getByLabelText("Title"), "x");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Bad Name");

    expect(screen.getByText(/lowercase letters/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save memory" })).toBeDisabled();
  });

  it("starts from a title it was opened with", () => {
    open({ initialTitle: "Onboarding notes" });
    expect(screen.getByLabelText("Title")).toHaveValue("Onboarding notes");
    expect(screen.getByLabelText("Name")).toHaveValue("onboarding-notes");
  });
});
