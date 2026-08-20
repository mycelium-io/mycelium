// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const baseMemory: Memory = {
  key: "context/overview",
  value: "Hello world",
  content_text: "Hello world",
  version: 3,
  created_by: "alice",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderEditor(overrides?: {
  onSaved?: () => void;
  onCancel?: () => void;
  memory?: Memory;
}) {
  const onSaved = overrides?.onSaved ?? vi.fn();
  const onCancel = overrides?.onCancel ?? vi.fn();
  const memory = overrides?.memory ?? baseMemory;
  render(
    <SWRTestCache>
      <MemoryEditor
        memory={memory}
        roomName="test-room"
        actor="alice"
        onSaved={onSaved}
        onCancel={onCancel}
      />
    </SWRTestCache>,
  );
  return { onSaved, onCancel };
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("MemoryEditor", () => {
  beforeEach(() => {
    vi.mocked(createMemories).mockResolvedValue(undefined);
  });

  it("shows the memory key read-only and the editor body", () => {
    renderEditor();
    expect(screen.getByText("context/overview")).toBeInTheDocument();
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

  it("includes expandable: true in meta when the checkbox is checked", async () => {
    const user = userEvent.setup();
    const memWithExpandable: Memory = {
      ...baseMemory,
      value: { expandable: true, text: "Hello" },
      content_text: "Hello",
    };
    renderEditor({ memory: memWithExpandable });
    // Checkbox should start checked.
    expect(screen.getByRole("checkbox", { name: /expandable/i })).toBeChecked();
    // Save — meta should carry expandable.
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(createMemories).toHaveBeenCalledWith("test-room", [
        expect.objectContaining({ meta: { expandable: true } }),
      ]);
    });
  });
});
