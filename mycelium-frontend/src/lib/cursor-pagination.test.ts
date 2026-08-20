// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { mergeOlder } from "@/lib/cursor-pagination";

interface Row {
  id: string | null;
  text: string;
}

const key = (row: Row) => row.id;

describe("mergeOlder", () => {
  it("puts a page of history in front of what is already on screen", () => {
    const onScreen = [{ id: "c", text: "third" }];
    const older = [
      { id: "a", text: "first" },
      { id: "b", text: "second" },
    ];

    expect(mergeOlder(onScreen, older, key).map((r) => r.text)).toEqual([
      "first",
      "second",
      "third",
    ]);
  });

  it("shows a message once when a page and the live stream both carry it", () => {
    // The overlap is by design: SSE keeps delivering while a page is in flight.
    const onScreen = [{ id: "b", text: "second" }];
    const older = [
      { id: "a", text: "first" },
      { id: "b", text: "second" },
    ];

    expect(mergeOlder(onScreen, older, key).map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("drops repeats inside a single page too", () => {
    const older = [
      { id: "a", text: "first" },
      { id: "a", text: "first again" },
    ];

    expect(mergeOlder([], older, key)).toHaveLength(1);
  });

  it("keeps a row with no id rather than losing that piece of history", () => {
    const older = [
      { id: null, text: "unidentified" },
      { id: null, text: "also unidentified" },
    ];

    expect(mergeOlder([], older, key)).toHaveLength(2);
  });

  it("returns the same list when a page adds nothing, so React can skip the render", () => {
    const onScreen = [{ id: "a", text: "first" }];

    expect(mergeOlder(onScreen, [{ id: "a", text: "first" }], key)).toBe(onScreen);
  });

  it("leaves the list alone when there is no older page", () => {
    const onScreen = [{ id: "a", text: "first" }];

    expect(mergeOlder(onScreen, [], key)).toBe(onScreen);
  });
});
