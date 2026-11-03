// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// An agent's session drawn as what it did: reads fold, only the latest plan
// shows, a failed call says so, and the bottom line claims only what the
// pane's state says.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentSessionView, SessionUnavailable } from "@/components/agent-session-view";
import type { AgentSession, SessionEntry, ToolCall } from "@/lib/agent-session";

let n = 0;
const meta = () => ({ id: `e${++n}`, at: "2026-11-03T12:00:00Z" });

function call(kind: ToolCall["kind"], title: string, over: Partial<ToolCall> = {}): ToolCall {
  return { sessionUpdate: "tool_call", toolCallId: `t${n}`, title, kind, status: "completed", _meta: meta(), ...over };
}

function plan(statuses: ("pending" | "in_progress" | "completed")[]): SessionEntry {
  return {
    sessionUpdate: "plan",
    entries: statuses.map((status, i) => ({ content: `Step ${i + 1}`, priority: "high" as const, status })),
    _meta: meta(),
  };
}

function session(entries: SessionEntry[], over: Partial<AgentSession> = {}): AgentSession {
  return { version: 1, sessionId: "s1", title: null, state: "idle", waitingOn: null, entries, earlier: false, ...over };
}

describe("AgentSessionView", () => {
  it("folds reads in a row into one line that opens to each", () => {
    render(
      <AgentSessionView
        session={session([call("read", "a.ts"), call("read", "b.ts"), call("execute", "npm test")])}
        onShowTerminal={vi.fn()}
      />,
    );
    expect(screen.queryByText("a.ts")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Read 2 files/ }));
    expect(screen.getByText("a.ts")).toBeTruthy();
    expect(screen.getByText("npm test")).toBeTruthy();
  });

  it("shows only the latest plan", () => {
    render(
      <AgentSessionView
        session={session([plan(["in_progress", "pending"]), plan(["completed", "in_progress"])])}
        onShowTerminal={vi.fn()}
      />,
    );
    expect(screen.getAllByText("Step 1")).toHaveLength(1);
    expect(screen.getByText("1/2")).toBeTruthy();
  });

  it("opens an edit to its diff, counted from the old and new text", () => {
    render(
      <AgentSessionView
        session={session([
          call("edit", "charge.ts", {
            content: [{ type: "diff", path: "charge.ts", oldText: "a\nb", newText: "a\nc\nd" }],
          }),
        ])}
        onShowTerminal={vi.fn()}
      />,
    );
    const row = screen.getByRole("button", { name: /charge\.ts/ });
    expect(row).toHaveTextContent("+2");
    expect(row).toHaveTextContent("−1");
    fireEvent.click(row);
    expect(screen.getByText("- b")).toBeTruthy();
  });

  it("marks a failed call, and one someone stopped, differently", () => {
    render(
      <AgentSessionView
        session={session([
          call("execute", "npm test", { status: "failed" }),
          call("execute", "npm run e2e", { status: "failed", _meta: { ...meta(), interrupted: true } }),
        ])}
        onShowTerminal={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Failed")).toBeTruthy();
    expect(screen.getByLabelText("Stopped")).toBeTruthy();
  });

  it("sends a waiting agent's question to its terminal", () => {
    const onShowTerminal = vi.fn();
    render(
      <AgentSessionView
        session={session([], { state: "waiting", waitingOn: "Allow it to run gh pr create?" })}
        onShowTerminal={onShowTerminal}
      />,
    );
    expect(screen.getByText("Allow it to run gh pr create?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Answer in its terminal" }));
    expect(onShowTerminal).toHaveBeenCalled();
  });

  it("shows a long prompt's first lines until it's opened", () => {
    const text = Array.from({ length: 30 }, (_, i) => `line ${i + 1}`).join("\n");
    render(
      <AgentSessionView
        session={session([{ sessionUpdate: "user_message", content: [{ type: "text", text }], _meta: { ...meta(), from: "person" } }])}
        onShowTerminal={vi.fn()}
      />,
    );
    expect(screen.queryByText(/line 30/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all 30 lines" }));
    expect(screen.getByText(/line 30/)).toBeTruthy();
  });

  it("claims nothing about a pane whose state it can't read", () => {
    render(<AgentSessionView session={session([], { state: "unknown" })} onShowTerminal={vi.fn()} />);
    expect(screen.queryByText("Working")).toBeNull();
    expect(screen.queryByRole("button", { name: "Answer in its terminal" })).toBeNull();
  });
});

describe("SessionUnavailable", () => {
  it("says a CLI can't be read yet, with where to add it", () => {
    render(<SessionUnavailable reason="no_converter" cli="opencode" onShowTerminal={vi.fn()} />);
    expect(screen.getByText("Mycelium can't read opencode sessions yet.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add support" })).toBeTruthy();
  });

  it("says a session can't be found, and goes back to the terminal", () => {
    const onShowTerminal = vi.fn();
    render(<SessionUnavailable reason="no_session" cli="Claude Code" onShowTerminal={onShowTerminal} />);
    expect(screen.getByText("Mycelium can't find where Claude Code keeps this session.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Add support" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show its terminal" }));
    expect(onShowTerminal).toHaveBeenCalled();
  });
});
