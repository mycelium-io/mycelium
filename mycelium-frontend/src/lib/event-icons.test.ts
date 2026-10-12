// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Every kind of event line has an icon, and the chat and the Stream tab draw
// them from the same table. The kinds are read from the frozen contract rather
// than copied here, so a new notice subkind or pull request change can't arrive
// without an icon.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NOTICE_ICONS, UPSTREAM_ICONS, noticeIcon } from "@/lib/event-icons";

const contract = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../contracts/slim-wire.json"), "utf-8"),
) as { notice: { subkinds: string[]; upstream_changes: string[] } };

const source = (file: string) => readFileSync(path.resolve(__dirname, "..", file), "utf-8");

describe("event icons", () => {
  it("has an icon and a label for every notice subkind in the contract", () => {
    for (const subkind of contract.notice.subkinds) {
      if (subkind === "upstream") continue; // drawn by its change, below
      expect(NOTICE_ICONS[subkind], subkind).toBeDefined();
      expect(NOTICE_ICONS[subkind].label).not.toBe("");
    }
  });

  it("has an icon and a label for every pull request change in the contract", () => {
    for (const change of contract.notice.upstream_changes) {
      expect(UPSTREAM_ICONS[change], change).toBeDefined();
      expect(noticeIcon("upstream", change)).toBe(UPSTREAM_ICONS[change]);
    }
  });

  it("keeps the colors' meaning: green lands, red is stuck, yellow is back up for grabs", () => {
    expect(noticeIcon("resolved").tone).toBe("var(--green)");
    expect(noticeIcon("blocked").tone).toBe("var(--red)");
    expect(noticeIcon("expired").tone).toBe("var(--yellow)");
    expect(noticeIcon("claimed").tone).toBe("var(--accent)");
    expect(noticeIcon("upstream", "ci_failed").tone).toBe("var(--red)");
    expect(noticeIcon("upstream", "merged").tone).toBe("var(--green)");
  });

  it("gives a filed decision its own icon", () => {
    expect(noticeIcon("filed", null, "decision").label).toBe("Decision filed");
    expect(noticeIcon("filed", null, "action").label).toBe("Task filed");
  });

  it("is the one table both the chat and the Stream tab read", () => {
    for (const file of ["components/event-stream.tsx", "components/stream/room-stream.tsx"]) {
      const code = source(file);
      expect(code, file).toMatch(/from "@\/lib\/event-icons"/);
      expect(code, file).toMatch(/noticeIcon\(/);
    }
    // The chat's old plain dot is gone.
    expect(source("components/event-stream.tsx")).not.toMatch(/\bdot=/);
  });
});
