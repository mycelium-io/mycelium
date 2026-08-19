// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { EMPTY_SCOPE, hasScope, parseFocus, resultHref, scopeChips, type SearchHit } from "@/lib/search";

const hit = (over: Partial<SearchHit> = {}): SearchHit => ({
  type: "memory",
  room: "atlas migration",
  id: "decisions/db choice",
  title: "decisions/db choice",
  subtitle: "",
  snippet: "",
  kind: null,
  timestamp: "",
  score: 1,
  ...over,
});

describe("result links", () => {
  it("sends a room result straight to the room", () => {
    expect(resultHref(hit({ type: "room", id: "atlas", room: "atlas" }))).toBe("/room/atlas");
  });

  it("opens memory hits on the full-page route (#614)", () => {
    const href = resultHref(hit());
    expect(href).toBe("/room/atlas%20migration/memory/decisions/db%20choice");
  });

  it("carries non-memory items as one focus parameter, round-tripping through the URL", () => {
    const href = resultHref(hit({ type: "episode", id: "ep-1" }));
    const focus = new URL(href, "http://x").searchParams.get("focus");
    expect(parseFocus(focus)).toEqual({ type: "episode", id: "ep-1" });
  });

  it("escapes a room name so a space can't end the path", () => {
    expect(resultHref(hit({ type: "episode", id: "ep-1" }))).toContain("/room/atlas%20migration?");
  });

  it("keeps the colons inside a memory key out of the type split", () => {
    expect(parseFocus("memory:log/episodes/a1:b2")).toEqual({
      type: "memory",
      id: "log/episodes/a1:b2",
    });
  });

  it("ignores a focus it can't act on rather than throwing", () => {
    expect(parseFocus(null)).toBeNull();
    expect(parseFocus("")).toBeNull();
    expect(parseFocus("nonsense")).toBeNull();
    expect(parseFocus("memory:")).toBeNull();
    expect(parseFocus(":abc")).toBeNull();
    expect(parseFocus("planet:mars")).toBeNull();
  });
});

describe("scope chips", () => {
  it("is quiet when the query carried no tokens", () => {
    expect(hasScope(EMPTY_SCOPE)).toBe(false);
    expect(hasScope({ ...EMPTY_SCOPE, text: "postgres" })).toBe(false);
  });

  it("draws each token back in the notation it was typed in", () => {
    const chips = scopeChips({
      text: "postgres",
      rooms: ["atlas"],
      actors: ["avery"],
      types: ["memory"],
      kinds: ["converged"],
    });
    expect(chips).toEqual(["#atlas", "@avery", "memory:", "kind:converged"]);
  });
});
