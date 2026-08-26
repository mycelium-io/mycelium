// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchMemoryGraph: vi.fn(),
  fetchMemory: vi.fn(),
  fetchMemoryExpanded: vi.fn().mockResolvedValue({ found: false, rendered: "", expansions: [], key: "" }),
  // MemoryDetail loads the selected memory's links on mount.
  fetchMemoryLinks: vi.fn().mockResolvedValue({ outbound: [], backlinks: [] }),
}));

import { MemoryGraphView } from "@/components/memory-graph-view";
import {
  fetchMemory,
  fetchMemoryExpanded,
  fetchMemoryGraph,
  type Memory,
  type MemoryGraph,
} from "@/lib/api";

const mockGraph = vi.mocked(fetchMemoryGraph);
const mockMemory = vi.mocked(fetchMemory);
const mockExpanded = vi.mocked(fetchMemoryExpanded);

const POPULATED: MemoryGraph = {
  nodes: [
    { key: "decisions/cutover", expandable: false, outbound: 0, inbound: 1 },
    { key: "context/goal", expandable: false, outbound: 1, inbound: 0 },
  ],
  edges: [{ source: "context/goal", target: "decisions/cutover", kind: "wikilink", resolved: true }],
};

function memory(key: string): Memory {
  return {
    key,
    value: null,
    content_text: `# ${key}\n\nbody text`,
    version: 3,
    created_by: "alice",
    updated_at: "2026-08-19T12:00:00Z",
  };
}

describe("<MemoryGraphView />", () => {
  beforeEach(() => {
    mockGraph.mockReset();
    mockMemory.mockReset();
    mockExpanded.mockReset().mockResolvedValue({ key: "", rendered: "", expansions: [], found: false });
  });

  it("renders the graph once the payload arrives", async () => {
    mockGraph.mockResolvedValue(POPULATED);
    render(<MemoryGraphView roomName="atlas" />);

    expect(await screen.findByRole("group", { name: /memory link graph/i })).toBeInTheDocument();
    expect(mockGraph).toHaveBeenCalledWith("atlas");
  });

  it("opens a clicked node in the drawer, over the graph", async () => {
    mockGraph.mockResolvedValue(POPULATED);
    mockMemory.mockResolvedValue(memory("decisions/cutover"));
    render(<MemoryGraphView roomName="atlas" />);

    const node = await screen.findByRole("button", { name: "Open decisions/cutover" });
    await userEvent.click(node);

    expect(mockMemory).toHaveBeenCalledWith("atlas", "decisions/cutover");
    // The drawer's own header carries the key and the version/author subtitle.
    expect(await screen.findByText("v3 · alice")).toBeInTheDocument();
    // ...and the graph is still mounted underneath, so pan/zoom and any
    // hand-arranged layout survive reading a memory.
    expect(screen.getByRole("group", { name: /memory link graph/i })).toBeInTheDocument();
  });

  it("closes the drawer and leaves the graph in place", async () => {
    mockGraph.mockResolvedValue(POPULATED);
    mockMemory.mockResolvedValue(memory("decisions/cutover"));
    render(<MemoryGraphView roomName="atlas" />);

    await userEvent.click(await screen.findByRole("button", { name: "Open decisions/cutover" }));
    await screen.findByText("v3 · alice");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByText("v3 · alice")).not.toBeInTheDocument());
    expect(screen.getByRole("group", { name: /memory link graph/i })).toBeInTheDocument();
  });

  it("resolves a node by key rather than a preloaded list", async () => {
    // The graph payload carries only keys, so every node has to be openable via
    // a fetch — this is why the rail's "find it in `memories`" lookup, which
    // silently no-ops for anything past the first page, isn't reused here.
    mockGraph.mockResolvedValue(POPULATED);
    mockMemory.mockResolvedValue(memory("context/goal"));
    render(<MemoryGraphView roomName="atlas migration" />);

    await userEvent.click(await screen.findByRole("button", { name: "Open context/goal" }));

    expect(mockMemory).toHaveBeenCalledWith("atlas migration", "context/goal");
  });

  it("shows the transcluded body, like the rail and the full page do", async () => {
    // Without this the drawer renders `![[…]]` as an unexpanded chip, so the
    // same memory reads differently depending on which surface opened it.
    mockGraph.mockResolvedValue(POPULATED);
    mockMemory.mockResolvedValue({ ...memory("decisions/cutover"), content_text: "before ![[context/goal]] after" });
    mockExpanded.mockResolvedValue({
      key: "decisions/cutover",
      rendered: "before THE EMBEDDED GOAL after",
      expansions: [],
      found: true,
    });
    render(<MemoryGraphView roomName="atlas" />);

    await userEvent.click(await screen.findByRole("button", { name: "Open decisions/cutover" }));

    expect(mockExpanded).toHaveBeenCalledWith("atlas", "decisions/cutover");
    expect(await screen.findByText(/THE EMBEDDED GOAL/)).toBeInTheDocument();
  });

  it("ignores a slow first request when a second memory has been opened", async () => {
    // Opening is two requests, and clicks can overlap. Without a guard the first
    // memory's body can land after the second's and the drawer titles itself one
    // memory while rendering another's text.
    mockGraph.mockResolvedValue(POPULATED);
    const slow: { resolve: (v: { key: string; rendered: string; expansions: []; found: boolean }) => void } = {
      resolve: () => {},
    };
    mockMemory.mockImplementation(async (_room, key) => memory(key));
    mockExpanded
      .mockImplementationOnce(() => new Promise(res => (slow.resolve = res)))
      .mockResolvedValue({ key: "context/goal", rendered: "SECOND BODY", expansions: [], found: true });

    render(<MemoryGraphView roomName="atlas" />);
    await userEvent.click(await screen.findByRole("button", { name: "Open decisions/cutover" }));
    await userEvent.click(screen.getByRole("button", { name: "Open context/goal" }));
    expect(await screen.findByText(/SECOND BODY/)).toBeInTheDocument();

    // The abandoned first request finally answers.
    await act(async () => {
      slow.resolve({ key: "decisions/cutover", rendered: "FIRST BODY", expansions: [], found: true });
    });

    expect(screen.queryByText(/FIRST BODY/)).not.toBeInTheDocument();
    expect(screen.getByText(/SECOND BODY/)).toBeInTheDocument();
  });

  it("keeps a saved arrangement across a reload of the whole view", async () => {
    // End-to-end for the persistence path, in the shape the real page takes: a
    // StrictMode mount where the graph arrives asynchronously, so the node only
    // exists after a fetch resolves. The component-level tests mount
    // <MemoryGraph> with its payload already in hand and would miss anything
    // that goes wrong in that ordering.
    const data = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => void data.set(k, v),
      removeItem: (k: string) => void data.delete(k),
    });
    mockGraph.mockResolvedValue(POPULATED);

    const first = render(
      <StrictMode>
        <MemoryGraphView roomName="atlas" />
      </StrictMode>,
    );
    const canvas = await screen.findByRole("group", { name: /memory link graph/i });
    canvas.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 700, right: 1000, bottom: 700, x: 0, y: 0 }) as DOMRect;

    const target = screen.getByRole("button", { name: "Open context/goal" });
    const opts = { bubbles: true, pointerId: 1, clientX: 100, clientY: 100 };
    act(() => {
      target.dispatchEvent(new PointerEvent("pointerdown", opts));
      canvas.dispatchEvent(new PointerEvent("pointermove", { ...opts, clientX: 240, clientY: 170 }));
      canvas.dispatchEvent(new PointerEvent("pointerup", { ...opts, clientX: 240, clientY: 170 }));
    });
    const arranged = screen.getByRole("button", { name: "Open context/goal" }).getAttribute("transform");
    first.unmount();

    render(
      <StrictMode>
        <MemoryGraphView roomName="atlas" />
      </StrictMode>,
    );

    const reloaded = await screen.findByRole("button", { name: "Open context/goal" });
    expect(reloaded.getAttribute("transform")).toBe(arranged);
    vi.unstubAllGlobals();
  });

  it("does not claim the room is empty when the graph payload is", async () => {
    // `fetchMemoryGraph` degrades to an empty graph for an unreachable hub or a
    // room whose link index was never built, so this state cannot honestly say
    // "no memories" — the Memory rail may well be listing plenty.
    mockGraph.mockResolvedValue({ nodes: [], edges: [] });
    render(<MemoryGraphView roomName="atlas" />);

    await waitFor(() => expect(screen.getByText(/no link graph for this room/i)).toBeInTheDocument());
    expect(screen.queryByText(/no memories/i)).not.toBeInTheDocument();
    expect(screen.getByText(/memory reindex/i)).toBeInTheDocument();
  });
});
