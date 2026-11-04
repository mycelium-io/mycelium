// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Earlier sessions to bring in: told apart by the titles the desktop app reads
// here, or by the member a session was started as; found by either.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentSessionSummary, Framework, Runner } from "@/lib/api";
import { EarlierSessions, sessionKey, type EarlierSession } from "@/components/earlier-sessions";
import { titleKey } from "@/lib/session-titles";

const runner = { id: "r1", label: "morgans-mbp", roots: ["/Users/morgan/code"] } as unknown as Runner;
const framework = { id: "claude", name: "Claude Code", installed: true } as Framework;

function session(id: string, over: Partial<AgentSessionSummary> = {}): EarlierSession {
  return {
    runner,
    framework,
    session: { id, folder: "/Users/morgan/code/shop", last_used: "2026-11-03T12:00:00Z", branch: "main", ...over },
  };
}

const sessions = [
  session("a"),
  session("b", { member: { room: "checkout", handle: "scout" } }),
  session("c", { branch: "fix/double-charge" }),
];

function draw(titles: ReadonlyMap<string, string>, onPick = vi.fn()) {
  render(<EarlierSessions sessions={sessions} titles={titles} picked={null} onPick={onPick} />);
  return onPick;
}

describe("EarlierSessions", () => {
  it("names each session by the title the app read here, or the member it was started as", () => {
    draw(new Map([[titleKey("claude", "a"), "Fix the refund webhook"], [titleKey("claude", "b"), "Mycelium room setup"]]));
    expect(screen.getByRole("radio", { name: "Fix the refund webhook" })).toBeTruthy();
    // A member's name leads, with its title under it.
    const member = screen.getByRole("radio", { name: "scout in checkout" });
    expect(member).toHaveTextContent("Mycelium room setup");
    expect(screen.getByRole("radio", { name: /Claude Code session in/ })).toHaveTextContent("Untitled session");
    expect(screen.queryByText(/title shows in the desktop app/)).toBeNull();
  });

  it("says where titles show when none could be read here", () => {
    draw(new Map());
    expect(screen.getByText("A session's title shows in the desktop app on the machine it's on.")).toBeTruthy();
    // A member's session is still named.
    expect(screen.getByRole("radio", { name: "scout in checkout" })).toBeTruthy();
  });

  it("finds a session by its title, its member or its branch, and picks it", () => {
    const onPick = draw(new Map([[titleKey("claude", "a"), "Fix the refund webhook"]]));
    const find = screen.getByRole("textbox", { name: "Find a session" });
    fireEvent.change(find, { target: { value: "refund" } });
    expect(screen.getAllByRole("radio")).toHaveLength(1);
    fireEvent.change(find, { target: { value: "scout" } });
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual(["scout in checkout"]);
    fireEvent.change(find, { target: { value: "double-charge" } });
    fireEvent.click(screen.getByRole("radio"));
    expect(onPick).toHaveBeenCalledWith(sessionKey(sessions[2]));
  });
});
