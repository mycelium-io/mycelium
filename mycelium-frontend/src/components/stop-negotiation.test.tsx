// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EpisodeSummary } from "@/lib/api";

// A plain function rather than a `vi.fn`: vitest's own tracking of a vi.fn
// that rejects leaves the rejection unhandled even when the caller catches it.
const calls: unknown[][] = [];
let answer: () => Promise<unknown> = async () => ({ stopped: true });
vi.mock("@/lib/api", () => ({
  stopNegotiation: (...a: unknown[]) => {
    calls.push(a);
    return answer();
  },
}));
vi.mock("@/components/current-user", () => ({ useCurrentUser: () => ({ principal: "julia" }) }));
vi.mock("@/components/status-items", () => ({
  StatusButton: ({ children, onClick }: { children: React.ReactNode; onClick: () => void }) => (
    <button type="button" onClick={onClick}>
      {children}
    </button>
  ),
}));

import { StopNegotiation, alignerRunning } from "./stop-negotiation";

const open = { short_id: "live", outcome: "open", subkind: null, flow: null } as unknown as EpisodeSummary;
const flowRun = { ...open, flow: { nodes: [] } } as unknown as EpisodeSummary;
const done = { ...open, outcome: "rejected", subkind: "rejected" } as unknown as EpisodeSummary;

describe("StopNegotiation", () => {
  beforeEach(() => {
    calls.length = 0;
    answer = async () => ({ stopped: true });
  });

  it("shows only while the aligner's negotiation is running", () => {
    expect(alignerRunning([open])).toBe(true);
    expect(alignerRunning([done])).toBe(false);
    expect(alignerRunning([flowRun])).toBe(false); // a conductor run isn't what Stop ends
    expect(alignerRunning(null)).toBe(false);

    const { container } = render(<StopNegotiation roomName="atlas" episodes={[done]} onStopped={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("stops it as you, then re-reads the room", async () => {
    const onStopped = vi.fn();
    render(<StopNegotiation roomName="atlas" episodes={[open]} onStopped={onStopped} />);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(onStopped).toHaveBeenCalled());
    expect(calls).toEqual([["atlas", "julia"]]);
  });

  it("re-reads the room even when it had already ended", async () => {
    answer = () => Promise.reject(new Error("No negotiation is running in atlas."));
    const onStopped = vi.fn();
    render(<StopNegotiation roomName="atlas" episodes={[open]} onStopped={onStopped} />);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => expect(onStopped).toHaveBeenCalled());
  });
});
