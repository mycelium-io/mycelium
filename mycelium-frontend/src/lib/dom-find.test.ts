// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { findRanges } from "@/lib/dom-find";

function page(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  return root;
}

describe("findRanges", () => {
  it("finds every hit in document order, folded for case", () => {
    const root = page("<p>Deploy the <b>deploy</b> script</p><p>then DEPLOY again</p>");
    expect(findRanges(root, "deploy").map(r => r.toString())).toEqual(["Deploy", "deploy", "DEPLOY"]);
  });

  it("marks each word of a query", () => {
    const root = page("<p>apple pie and cherry tart</p>");
    expect(findRanges(root, ["cherry", "apple"]).map(r => r.toString())).toEqual(["apple", "cherry"]);
  });

  it("never searches the find bar, a field, or what's hidden from readers", () => {
    const root = page(
      '<div data-find-skip><input value="deploy">deploy</div><textarea>deploy</textarea><span aria-hidden="true">deploy</span><p>deploy</p>',
    );
    expect(findRanges(root, "deploy")).toHaveLength(1);
  });

  it("finds nothing for an empty query", () => {
    expect(findRanges(page("<p>anything</p>"), "  ")).toHaveLength(0);
  });
});
