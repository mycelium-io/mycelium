// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Every kind of event line has an icon. The kinds are read from the frozen
// contracts rather than copied here, so a new notice subkind, pull request
// change or board kind can't arrive without one.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FILED_ICONS, NOTICE_ICONS, UPSTREAM_ICONS, noticeIcon } from "@/lib/event-icons";
import { noticeLabel } from "@/lib/threads";

const contract = <T,>(name: string): T =>
  JSON.parse(readFileSync(path.resolve(__dirname, "../../../contracts", name), "utf-8")) as T;
const wire = contract<{ notice: { subkinds: string[]; upstream_changes: string[] } }>("slim-wire.json");
const board = contract<{ kinds: string[] }>("board-vocabulary.json");

describe("event icons", () => {
  it("has an icon and a label for every notice subkind in the contract", () => {
    for (const subkind of wire.notice.subkinds) {
      if (subkind === "upstream") continue; // drawn by its change, below
      expect(NOTICE_ICONS[subkind], subkind).toBeDefined();
      expect(NOTICE_ICONS[subkind].label).not.toBe("");
    }
  });

  it("has an icon and a label for every pull request change in the contract", () => {
    for (const change of wire.notice.upstream_changes) {
      expect(UPSTREAM_ICONS[change], change).toBeDefined();
      expect(noticeIcon("upstream", change)).toBe(UPSTREAM_ICONS[change]);
    }
  });

  it("gives every kind of filed row an icon labelled with the line's own words", () => {
    for (const kind of board.kinds) {
      const icon = noticeIcon("filed", null, kind);
      expect(icon, kind).toBe(FILED_ICONS[kind]);
      // "New blocker" beside a "New blocker" icon, never "Task filed".
      expect(icon.label, kind).toBe(noticeLabel("filed", kind));
    }
  });

  it("keeps the colors' meaning: green lands, red is stuck, yellow is back up for grabs", () => {
    expect(noticeIcon("resolved").tone).toBe("var(--green)");
    expect(noticeIcon("blocked").tone).toBe("var(--red)");
    expect(noticeIcon("filed", null, "blocked").tone).toBe("var(--red)");
    expect(noticeIcon("expired").tone).toBe("var(--yellow)");
    expect(noticeIcon("claimed").tone).toBe("var(--accent)");
    expect(noticeIcon("upstream", "ci_failed").tone).toBe("var(--red)");
    expect(noticeIcon("upstream", "merged").tone).toBe("var(--green)");
  });
});
