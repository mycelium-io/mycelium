// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";
import { resetStreamHub } from "@/lib/stream-hub";

vi.mock("@/lib/api", () => ({
  fetchEpisodes: vi.fn().mockResolvedValue([]),
  fetchEpisode: vi.fn().mockResolvedValue(null),
  fetchWireHistory: vi.fn().mockResolvedValue([]),
  logFetchError: () => () => undefined,
}));

import { envelopeJson, MessageInspector, MetricsRow, toMessageFrame } from "@/components/message-inspector";
import { fetchWireHistory } from "@/lib/api";

const CREATED = "2026-08-04T10:00:00.000000+00:00";
/** A row's kind badge, not the kind toggle in the filter bar that shares its text. */
const ROW_KIND = "span[aria-description]";

// The real bus shape: the persister feeds each SLIM-ingested message as
// `l9_<kind>` with the bare message (header + payload) as its content.
function commitMessage() {
  return {
    message_type: "l9_commit",
    sender_handle: "aligner",
    created_at: CREATED,
    content: JSON.stringify({
      header: {
        kind: "commit",
        subkind: "converged",
        message: {
          id: "abcdef123456",
          parents: ["p1"],
          episode: "urn:ioc:mycelium:episode:sprint:s1",
        },
      },
      payload: {
        type: "consensus",
        data: {
          assignments: { scope: "mvp" },
          metrics: { mpc: 0.91, gar: 1.0, scr: 0.0, provenance_weight: 1.0 },
        },
      },
    }),
  };
}

function knowledgeMessage() {
  return {
    message_type: "l9_knowledge",
    sender_handle: "alice",
    created_at: "2026-08-04T10:00:01.000000+00:00",
    content: JSON.stringify({
      header: { kind: "knowledge", subkind: "distillation", message: { id: "know01" } },
      payload: { type: "data", data: { key: "decisions/scope" } },
    }),
  };
}

/** A frame as a flow's run puts it on the wire: its kind, payload type and data. */
function wire(sender: string, kind: string, type: string, data: Record<string, unknown>, subkind?: string) {
  return {
    message_type: `l9_${kind}`,
    sender_handle: sender,
    created_at: CREATED,
    content: JSON.stringify({
      header: { kind, subkind: subkind ?? null, message: { id: `${sender}-${type}-${Math.random()}` } },
      payload: { type, data },
    }),
  };
}

describe("a flow's run reads as its steps, not as a column of exchanges", () => {
  it("says which step a conductor turn is and who it went to", () => {
    const frame = toMessageFrame(
      wire("conductor", "exchange", "message", {
        conductor: { event: "turn", step: "propose", to: "success", turn: 1, cap: 9 },
      }),
    );
    expect(frame?.summary).toBe("propose → success · turn 1 of 9");
  });

  it("says what a pick chose, how low it was, and where it went next", () => {
    const frame = toMessageFrame(
      wire("conductor", "exchange", "message", {
        conductor: {
          event: "select",
          next: "repair",
          select: { outcome: "infeasible", pick: "B", lowest: 30, least_happy: "legal" },
        },
      }),
    );
    expect(frame?.summary).toBe("pick B · lowest 30 (legal) → repair");
  });

  it("says how a run ended on its commit", () => {
    const frame = toMessageFrame(
      wire(
        "conductor",
        "commit",
        "outcome",
        {
          conductor: { event: "close", outcome: "converged", pick: "F", steps: 6 },
          assignments: { decision: "Renew at current rates" },
          metrics: { satisfaction: { legal: 0.89, finance: 0.77 }, min_satisfaction: 0.77 },
        },
        "converged",
      ),
    );
    expect(frame?.summary).toBe("converged on F after 6 steps");
  });

  it("shows a reply's ratings, stance and confidence", () => {
    expect(toMessageFrame(wire("legal", "exchange", "reply", { scores: { A: 25, B: 88 } }))?.summary).toBe(
      "A=25 B=88",
    );
    expect(toMessageFrame(wire("legal", "exchange", "reply", { confidence: 0.8 }))?.summary).toBe(
      "confidence 0.8",
    );
    expect(
      toMessageFrame(wire("legal", "exchange", "reply", { action: "accept", confidence: 0.9 }))?.summary,
    ).toBe("accept · confidence 0.9");
  });

  it("says what a ping or a notice is", () => {
    expect(toMessageFrame(wire("system", "exchange", "ping", { episode: "e" }))?.summary).toBe(
      "ping: a thread moved",
    );
    expect(
      toMessageFrame(wire("system", "exchange", "notice", { subkind: "filed", key: "work/draft-terms" }))?.summary,
    ).toBe("notice: filed work/draft-terms");
  });

  it("shows the numbers a concord commit has, and no NaN for the ones it doesn't", () => {
    render(<MetricsRow metrics={{ satisfaction: { legal: 0.89 }, min_satisfaction: 0.77 } as never} />);
    expect(screen.getByText("0.77")).toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.queryByText("MPC")).not.toBeInTheDocument();
  });
});

describe("toMessageFrame", () => {
  it("reads kind/subkind/episode/parents from a bare persister envelope", () => {
    const frame = toMessageFrame(commitMessage());
    expect(frame).not.toBeNull();
    expect(frame?.kind).toBe("commit");
    expect(frame?.subkind).toBe("converged");
    expect(frame?.episode).toBe("urn:ioc:mycelium:episode:sprint:s1");
    expect(frame?.parents).toEqual(["p1"]);
    expect(frame?.metrics?.mpc).toBe(0.91);
  });

  it("also reads an envelope embedded under an `l9` key", () => {
    const frame = toMessageFrame({
      message_type: "coordination_consensus",
      sender_handle: "aligner",
      created_at: CREATED,
      content: JSON.stringify({
        l9: { header: { kind: "commit", subkind: "converged", message: { id: "x", episode: "urn:e" } } },
        metrics: { mpc: 0.8, gar: 1, scr: 0, provenance_weight: 1 },
      }),
    });
    expect(frame?.kind).toBe("commit");
    expect(frame?.metrics?.mpc).toBe(0.8);
  });

  it("falls back to message_type when no envelope is present", () => {
    const frame = toMessageFrame({
      message_type: "coordination_tick",
      sender_handle: "bob",
      created_at: CREATED,
      content: JSON.stringify({ payload: { round: 2, action: "counter" } }),
    });
    expect(frame?.kind).toBe("exchange");
    expect(frame?.summary).toContain("round 2");
  });

  it("derives the sender from the envelope actors when no flat sender_handle is present", () => {
    // A bare `{header, payload}` envelope (e.g. an episode-detail frame) carries
    // its sender as the first participant actor, not a flattened field.
    const frame = toMessageFrame({
      message_type: "l9_exchange",
      created_at: CREATED,
      content: JSON.stringify({
        header: {
          kind: "exchange",
          participants: { actors: [{ id: "growth", role: "agent" }, { id: "risk", role: "agent" }] },
          message: { id: "ex01" },
        },
        payload: { type: "reply", data: { action: "accept" } },
      }),
    });
    expect(frame?.sender).toBe("growth");
  });

  it("prefers the flat sender_handle over the envelope actors when both are present", () => {
    const frame = toMessageFrame({
      message_type: "l9_exchange",
      sender_handle: "alice",
      created_at: CREATED,
      content: JSON.stringify({
        header: {
          kind: "exchange",
          participants: { actors: [{ id: "growth", role: "agent" }] },
          message: { id: "ex02" },
        },
      }),
    });
    expect(frame?.sender).toBe("alice");
  });

  it("returns null for plain chat (non-protocol traffic)", () => {
    expect(toMessageFrame({ message_type: "broadcast", content: "hi there" })).toBeNull();
  });

  it("retains the raw wire message on the frame", () => {
    const msg = commitMessage();
    const frame = toMessageFrame(msg);
    expect(frame?.raw).toBe(msg);
  });
});

describe("envelopeJson", () => {
  it("decodes the transport-encoded content string into structure", () => {
    const json = envelopeJson(commitMessage());
    expect(json).toContain('"subkind": "converged"');
    expect(json).toContain('"scope": "mvp"');
    expect(json).toContain('"parents"');
    // The envelope must not remain a single escaped string.
    expect(json).not.toContain('\\"header\\"');
  });

  it("leaves non-JSON content untouched", () => {
    const json = envelopeJson({ message_type: "l9_exchange", content: "not json" });
    expect(json).toContain('"content": "not json"');
  });
});

describe("<MessageInspector />", () => {
  beforeEach(() => {
    resetStreamHub();
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("renders commit + knowledge wire frames with kind and metrics", async () => {
    render(<MessageInspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
      es.emit(knowledgeMessage());
    });

    // Commit verdict renders with its kind + the SIEP metrics.
    expect(await screen.findByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.getByText("MPC")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();

    // Knowledge push renders as its own frame.
    expect(screen.getByText(/^knowledge/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.getByText("decisions/scope")).toBeInTheDocument();
  });

  it("backfills history frames on mount, with no live event", async () => {
    vi.mocked(fetchWireHistory).mockResolvedValueOnce([commitMessage()]);
    render(<MessageInspector roomName="sprint" />);

    // The frame comes purely from the transcript replay — nothing emitted on SSE.
    expect(await screen.findByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.getByText("MPC")).toBeInTheDocument();
  });

  it("dedups a backfilled frame against its live re-push (same envelope id)", async () => {
    vi.mocked(fetchWireHistory).mockResolvedValueOnce([commitMessage()]);
    render(<MessageInspector roomName="sprint" />);
    expect(await screen.findByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();

    const es = FakeEventSource.latest();
    await act(async () => {
      es.open();
      es.emit(commitMessage()); // same id as the backfilled row
    });

    // Still exactly one commit row — the live push was deduped by frame id.
    expect(screen.getAllByText(/^commit/, { selector: ROW_KIND })).toHaveLength(1);
  });

  it("expands a wire row into the full envelope JSON and collapses it again", async () => {
    render(<MessageInspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
    });

    const row = await screen.findByRole("button", { name: /^commit/ });
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("frame-json")).not.toBeInTheDocument();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    const json = screen.getByTestId("frame-json");
    expect(json.textContent).toContain('"subkind": "converged"');
    expect(json.textContent).toContain('"episode": "urn:ioc:mycelium:episode:sprint:s1"');
    expect(json.textContent).toContain('"assignments"');

    fireEvent.click(row);
    expect(screen.queryByTestId("frame-json")).not.toBeInTheDocument();
  });

  it("keeps other rows collapsed when one row is expanded (row-local state)", async () => {
    render(<MessageInspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
      es.emit(knowledgeMessage());
    });

    fireEvent.click(await screen.findByRole("button", { name: /^commit/ }));
    expect(screen.getAllByTestId("frame-json")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /^knowledge/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("filters the wire by kind via the toggle chips", async () => {
    render(<MessageInspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
      es.emit(knowledgeMessage());
    });

    expect(await screen.findByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.getByText(/^knowledge/, { selector: ROW_KIND })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Toggle knowledge frames" }));
    expect(screen.getByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.queryByText(/^knowledge/, { selector: ROW_KIND })).not.toBeInTheDocument();

    // Toggling every kind off surfaces the filtered-empty state.
    fireEvent.click(screen.getByRole("button", { name: "Toggle commit frames" }));
    expect(screen.getByText("No frames match the current filters")).toBeInTheDocument();
  });

  it("filters the wire by episode via the select", async () => {
    render(<MessageInspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage()); // episode urn:ioc:mycelium:episode:sprint:s1
      es.emit(knowledgeMessage()); // no episode
    });

    expect(await screen.findByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter by episode"), {
      target: { value: "urn:ioc:mycelium:episode:sprint:s1" },
    });
    expect(screen.getByText(/^commit/, { selector: ROW_KIND })).toBeInTheDocument();
    expect(screen.queryByText(/^knowledge/, { selector: ROW_KIND })).not.toBeInTheDocument();
  });
});
