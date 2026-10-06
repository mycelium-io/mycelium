// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SWRTestCache } from "@/test/swr";
import { MemoryEditor } from "@/components/memory-editor";
import type { Memory } from "@/lib/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("@fedoup/markdown-editor", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return {
    MarkdownEditor: forwardRef(function MockMdEditor(
      { initialValue, onChange }: { initialValue: string; onChange?: (v: string) => void },
      ref: import("react").ForwardedRef<{ getValue: () => string; focus: () => void }>,
    ) {
      useImperativeHandle(ref, () => ({
        getValue: () => initialValue,
        focus: () => {},
      }));
      return (
        <textarea
          data-testid="md-editor"
          defaultValue={initialValue}
          onChange={e => onChange?.(e.target.value)}
        />
      );
    }),
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, createMemories: vi.fn() };
});

vi.mock("@/lib/room-data", () => ({
  useRoomMemories: () => ({ memories: [], loading: false }),
  useRoomRevalidate: () => vi.fn(),
}));

import { createMemories } from "@/lib/api";

// The API wraps every value in an object, so even plain prose arrives as
// `{text}` — the fixtures mirror that rather than using a bare string.
const baseMemory: Memory = {
  key: "context/overview",
  value: { text: "Hello world" },
  content_text: "Hello world",
  version: 3,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderEditor(overrides?: {
  onSaved?: () => void;
  onCancel?: () => void;
  onDirtyChange?: (dirty: boolean) => void;
  memory?: Memory;
}) {
  const onSaved = overrides?.onSaved ?? vi.fn();
  const onCancel = overrides?.onCancel ?? vi.fn();
  const onDirtyChange = overrides?.onDirtyChange ?? vi.fn();
  const memory = overrides?.memory ?? baseMemory;
  render(
    <SWRTestCache>
      <MemoryEditor
        memory={memory}
        roomName="test-room"
        actor="alice"
        onSaved={onSaved}
        onCancel={onCancel}
        onDirtyChange={onDirtyChange}
      />
    </SWRTestCache>,
  );
  return { onSaved, onCancel, onDirtyChange };
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("MemoryEditor", () => {
  beforeEach(() => {
    vi.mocked(createMemories).mockReset().mockResolvedValue(undefined);
    localStorage.clear();
  });

  it("saves on ⌘S", async () => {
    const { onSaved } = renderEditor();
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    await waitFor(() => expect(createMemories).toHaveBeenCalledOnce());
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("reads clean again when an edit is undone by hand", async () => {
    const { onDirtyChange } = renderEditor();
    const body = screen.getByTestId("md-editor");
    fireEvent.change(body, { target: { value: "Hello world!" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.change(body, { target: { value: "Hello world" } });
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("goes full screen over the app and comes back on Esc, keeping the edit", async () => {
    const user = userEvent.setup();
    renderEditor();
    fireEvent.change(screen.getByTestId("md-editor"), { target: { value: "Hello there" } });
    await user.click(screen.getByRole("button", { name: "Full screen" }));

    const screenDialog = screen.getByRole("dialog", { name: "Editing context/overview" });
    expect(screenDialog.parentElement).toBe(document.body);
    // A new editor, built from what was written.
    expect(screen.getByTestId("md-editor")).toHaveValue("Hello there");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("md-editor")).toHaveValue("Hello there");
  });

  it("toggles full screen with ⌘⇧F", () => {
    renderEditor();
    fireEvent.keyDown(window, { key: "F", metaKey: true, shiftKey: true });
    expect(screen.getByRole("button", { name: "Exit full screen" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "F", metaKey: true, shiftKey: true });
    expect(screen.getByRole("button", { name: "Full screen" })).toBeInTheDocument();
  });

  it("previews the body as readers will see it", async () => {
    const user = userEvent.setup();
    renderEditor({ memory: { ...baseMemory, content_text: "## Plan\n\nShip it." } });
    await user.click(screen.getByRole("radio", { name: "Preview" }));
    expect(screen.getByRole("heading", { name: "Plan" })).toBeInTheDocument();
    expect(screen.queryByTestId("md-editor")).not.toBeInTheDocument();
    // Formatting has nothing to act on in the preview.
    expect(screen.getByRole("button", { name: "Bold" })).toBeDisabled();
  });

  it("lists the body's links and calls out the ones that go nowhere", () => {
    renderEditor({ memory: { ...baseMemory, content_text: "See [[decisions/nope]] and ![[context/missing]]." } });
    expect(screen.getByText("decisions/nope")).toBeInTheDocument();
    expect(screen.getByText("2 not found", { exact: false })).toBeInTheDocument();
  });

  it("keeps an unsaved edit in this browser and offers it back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const first = render(
        <SWRTestCache>
          <MemoryEditor memory={baseMemory} roomName="test-room" onSaved={vi.fn()} onCancel={vi.fn()} />
        </SWRTestCache>,
      );
      fireEvent.change(screen.getByTestId("md-editor"), { target: { value: "Half a thought" } });
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      first.unmount();
    } finally {
      vi.useRealTimers();
    }

    const user = userEvent.setup();
    renderEditor();
    expect(screen.getByText(/You left unsaved changes here/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getByTestId("md-editor")).toHaveValue("Half a thought");
    expect(screen.queryByText(/You left unsaved changes here/)).not.toBeInTheDocument();
  });

  it("forgets the kept edit once it is saved", async () => {
    const user = userEvent.setup();
    renderEditor();
    fireEvent.change(screen.getByTestId("md-editor"), { target: { value: "Saved for real" } });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(createMemories).toHaveBeenCalled());
    expect(localStorage.length).toBe(0);
  });

  it("offers the text for copying when someone else saved first", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    vi.mocked(createMemories).mockRejectedValueOnce(new ApiError("conflict", 409));
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("button", { name: "Copy my text" })).toBeInTheDocument();
  });

  it("shows the memory key read-only and the editor body", () => {
    renderEditor();
    expect(screen.getByTitle("context/overview")).toHaveTextContent("context/overview");
    expect(screen.getByTestId("md-editor")).toHaveValue("Hello world");
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderEditor();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("calls createMemories and then onSaved on a successful save", async () => {
    const user = userEvent.setup();
    const { onSaved } = renderEditor();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ key: "context/overview", base_version: 3 }),
      ]);
    });
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("shows a conflict message on a 409 response", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    vi.mocked(createMemories).mockRejectedValueOnce(new ApiError("conflict", 409));
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(screen.getByText(/edited by someone else/i)).toBeInTheDocument();
    });
  });

  it("shows a generic error message on other failures", async () => {
    vi.mocked(createMemories).mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(screen.getByText("network down")).toBeInTheDocument();
    });
  });

  it("pre-populates tag chips from memory.tags", () => {
    const memWithTags: Memory = { ...baseMemory, tags: ["decision", "draft"] };
    renderEditor({ memory: memWithTags });
    expect(screen.getByText("decision")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
  });

  it("commits a tag typed into the input when Save is clicked without pressing Enter", async () => {
    const user = userEvent.setup();
    renderEditor();
    // Type a tag but do NOT press Enter — simulate clicking Save directly.
    await user.click(screen.getByRole("textbox", { name: /memory tags/i }));
    await user.keyboard("important");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ tags: ["important"] }),
      ]);
    });
  });

  it("reports clean until something is edited", async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderEditor();
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);

    await user.type(screen.getByTestId("md-editor"), "!");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
  });

  it("reports dirty when only a tag changes", async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderEditor();
    await user.click(screen.getByRole("textbox", { name: /memory tags/i }));
    await user.keyboard("urgent{Enter}");
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
  });

  it("reports dirty when only the expandable flag changes", async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderEditor();
    await user.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));
  });

  it("reports clean again once the save succeeds", async () => {
    const user = userEvent.setup();
    const { onDirtyChange } = renderEditor();
    await user.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  it("stays dirty when the save fails", async () => {
    vi.mocked(createMemories).mockRejectedValueOnce(new Error("network down"));
    const user = userEvent.setup();
    const { onDirtyChange } = renderEditor();
    await user.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
  });

  it("flattens a text-only memory back to a bare string", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ value: "Hello world" }),
      ]);
    });
  });

  it("preserves the extra fields of a structured memory", async () => {
    const user = userEvent.setup();
    // A category entry as the CLI writes it: prose plus bookkeeping fields
    // that the editor never shows and must not drop.
    const structured: Memory = {
      ...baseMemory,
      value: {
        text: "We chose Postgres.",
        logged_at: "2026-08-21T14:02:00Z",
        category: "decisions",
      },
      content_text: "We chose Postgres.",
    };
    renderEditor({ memory: structured });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({
          value: {
            text: "We chose Postgres.",
            logged_at: "2026-08-21T14:02:00Z",
            category: "decisions",
          },
        }),
      ]);
    });
  });

  it("reflects the memory's expandable flag in the checkbox", () => {
    renderEditor({ memory: { ...baseMemory, expandable: true } });
    expect(screen.getByRole("checkbox", { name: /expandable/i })).toBeChecked();
  });

  it("sends expandable: false when the flag is cleared", async () => {
    const user = userEvent.setup();
    renderEditor({ memory: { ...baseMemory, expandable: true } });
    await user.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    // Sent explicitly rather than omitted: the backend preserves unmanaged
    // frontmatter, so an absent flag would leave `expandable: true` on disk.
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ meta: { expandable: false } }),
      ]);
    });
  });

  it("sends expandable: true when the flag is set", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("checkbox", { name: /expandable/i }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ meta: { expandable: true } }),
      ]);
    });
  });
});
