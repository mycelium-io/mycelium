// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** ⌘F in any view: the hits in what a view has drawn, as text ranges.
 *
 *  The channel matches its messages as data, because it is a paged feed and a
 *  hit can be a message not drawn yet. Everywhere else what is on the page is
 *  what there is to find, so this reads the page: every text node under a
 *  root, matched the way the channel matches (`splitOnMatches`, literal and
 *  folded for case), and marks the hits with the CSS Custom Highlight API, so
 *  nothing the view renders has to know a search is open. */

import { splitOnMatches, type Needles } from "@/lib/chat-search";

/** Marks an element (and what's inside it) as never searched: the find bar itself. */
export const FIND_SKIP = "data-find-skip";

const SKIPPED = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "INPUT", "SELECT"]);

function searchable(node: Text, root: Node): boolean {
  for (let el = node.parentElement; el && el !== root; el = el.parentElement) {
    if (SKIPPED.has(el.tagName) || el.hasAttribute(FIND_SKIP) || el.getAttribute("aria-hidden") === "true") {
      return false;
    }
  }
  return true;
}

/** Every hit of `query` under `root`, in document order. A hit is found within
 *  one text node: a word split across two elements is two halves, not a hit. */
export function findRanges(root: Node, query: Needles): Range[] {
  const ranges: Range[] = [];
  const doc = root.ownerDocument ?? document;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    const text = node.data;
    if (!text.trim() || !searchable(node, root)) continue;
    let at = 0;
    for (const segment of splitOnMatches(text, query)) {
      if (segment.match) {
        const range = doc.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + segment.text.length);
        ranges.push(range);
      }
      at += segment.text.length;
    }
  }
  return ranges;
}

/** Whether this browser can mark ranges. Where it can't, find still counts and
 *  steps; the hit stood on is selected instead. */
export function canHighlight(): boolean {
  return typeof CSS !== "undefined" && "highlights" in CSS && typeof Highlight !== "undefined";
}

/** Each open find's hits, by the view that owns them. The page has one set of
 *  named highlights, so two views finding at once (a split, the board beside a
 *  memory) are drawn together rather than the later one wiping the other. */
const marked = new Map<object, { ranges: Range[]; active: Range | null }>();

function redraw(): void {
  const hits: Range[] = [];
  const active: Range[] = [];
  for (const entry of marked.values()) {
    for (const r of entry.ranges) if (r !== entry.active) hits.push(r);
    if (entry.active) active.push(entry.active);
  }
  CSS.highlights.set("find-hit", new Highlight(...hits));
  CSS.highlights.set("find-active", new Highlight(...active));
}

/** Draw `owner`'s `ranges` as hits, with `active` as the one stood on. Returns what puts them away. */
export function markRanges(owner: object, ranges: Range[], active: Range | null): () => void {
  if (!canHighlight()) {
    if (active) {
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(active);
    }
    return () => {};
  }
  marked.set(owner, { ranges, active });
  redraw();
  return () => {
    marked.delete(owner);
    redraw();
  };
}

/** Bring a hit into view, centered in whichever scroller holds it. */
export function revealRange(range: Range): void {
  const el = range.startContainer.parentElement;
  el?.scrollIntoView({ block: "center", behavior: "smooth" });
}
