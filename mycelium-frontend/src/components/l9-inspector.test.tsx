// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource } from "@/test/fake-event-source";

vi.mock("@/lib/api", () => ({
  fetchEpisodes: vi.fn().mockResolvedValue([]),
  fetchEpisode: vi.fn().mockResolvedValue(null),
  getSSEUrl: (room: string) => `/api/rooms/${room}/messages/stream`,
  logFetchError: () => () => undefined,
}));

import { envelopeJson, L9Inspector, toL9Frame } from "@/components/l9-inspector";

const CREATED = "2026-08-04T10:00:00.000000+00:00";

// The real bus shape: the persister feeds each SLIM-ingested message as
// `l9_<kind>` with the bare L9 envelope (header + payload) as its content.
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

describe("toL9Frame", () => {
  it("reads kind/subkind/episode/parents from a bare persister envelope", () => {
    const frame = toL9Frame(commitMessage());
    expect(frame).not.toBeNull();
    expect(frame?.kind).toBe("commit");
    expect(frame?.subkind).toBe("converged");
    expect(frame?.episode).toBe("urn:ioc:mycelium:episode:sprint:s1");
    expect(frame?.parents).toEqual(["p1"]);
    expect(frame?.metrics?.mpc).toBe(0.91);
  });

  it("also reads an envelope embedded under an `l9` key", () => {
    const frame = toL9Frame({
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
    const frame = toL9Frame({
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
    const frame = toL9Frame({
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
    const frame = toL9Frame({
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
    expect(toL9Frame({ message_type: "broadcast", content: "hi there" })).toBeNull();
  });

  it("retains the raw wire message on the frame", () => {
    const msg = commitMessage();
    const frame = toL9Frame(msg);
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

describe("<L9Inspector />", () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("renders commit + knowledge wire frames with kind and metrics", async () => {
    render(<L9Inspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
      es.emit(knowledgeMessage());
    });

    // Commit verdict renders with its kind + the SIEP metrics.
    expect(await screen.findByText(/^COMMIT/)).toBeInTheDocument();
    expect(screen.getByText("MPC")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();

    // Knowledge push renders as its own frame.
    expect(screen.getByText(/^KNOWLEDGE/)).toBeInTheDocument();
    expect(screen.getByText("decisions/scope")).toBeInTheDocument();
  });

  it("expands a wire row into the full envelope JSON and collapses it again", async () => {
    render(<L9Inspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
    });

    const row = await screen.findByRole("button", { name: /COMMIT/ });
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
    render(<L9Inspector roomName="sprint" />);
    const es = FakeEventSource.latest();

    await act(async () => {
      es.open();
      es.emit(commitMessage());
      es.emit(knowledgeMessage());
    });

    fireEvent.click(await screen.findByRole("button", { name: /COMMIT/ }));
    expect(screen.getAllByTestId("frame-json")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /KNOWLEDGE/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});
