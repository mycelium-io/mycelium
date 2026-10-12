// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import type { Upload } from "@/lib/api";
import { NO_FILTER, dayLabel, filterFiles, groupByDay, originLabel, postersIn, tasksIn } from "@/lib/room-files";

const THREAD = "urn:ioc:mycelium:episode:r:t1";

function file(name: string, at: string, extra: Partial<Upload> = {}): Upload {
  return {
    name,
    key: `uploads/${name}`,
    filename: name,
    kind: name.endsWith(".png") ? "image" : "pdf",
    content_type: "",
    size: 100,
    sha256: name,
    created_by: "julia",
    created_at: at,
    url: `/api/rooms/r/uploads/${name}/raw`,
    ...extra,
  };
}

const channel = { message_id: "m1", sender: "builder", at: "", episode: null };
const inTask = { message_id: "m2", sender: "julia", at: "", episode: THREAD, task: "work/settings", task_title: "Fix settings" };

const FILES = [
  file("old-plan.pdf", "2026-10-09T10:00:00"),
  file("shot-1.png", "2026-10-11T09:00:00", { posted_in: channel }),
  file("shot-2.png", "2026-10-11T15:00:00", { posted_in: inTask }),
  file("spec.pdf", "2026-10-10T12:00:00", { posted_in: inTask }),
];

describe("filterFiles", () => {
  it("lists every file newest first", () => {
    expect(filterFiles(FILES, NO_FILTER).map((u) => u.name)).toEqual(["shot-2.png", "shot-1.png", "spec.pdf", "old-plan.pdf"]);
  });

  it("narrows by kind, poster, where it was posted and name", () => {
    const names = (f: Partial<typeof NO_FILTER>) => filterFiles(FILES, { ...NO_FILTER, ...f }).map((u) => u.name);
    expect(names({ kind: "images" })).toEqual(["shot-2.png", "shot-1.png"]);
    expect(names({ kind: "other" })).toEqual(["spec.pdf", "old-plan.pdf"]);
    // The sender of its message, else whoever added it.
    expect(names({ by: "builder" })).toEqual(["shot-1.png"]);
    expect(names({ where: "channel" })).toEqual(["shot-1.png"]);
    expect(names({ where: { task: "work/settings" } })).toEqual(["shot-2.png", "spec.pdf"]);
    expect(names({ where: "memory" })).toEqual(["old-plan.pdf"]);
    expect(names({ query: "SHOT 2" })).toEqual(["shot-2.png"]);
  });

  it("offers the people and tasks the files came from", () => {
    expect(postersIn(FILES)).toEqual(["builder", "julia"]);
    expect(tasksIn(FILES)).toEqual([{ key: "work/settings", title: "Fix settings" }]);
  });
});

describe("groupByDay", () => {
  const now = new Date("2026-10-11T18:00:00");

  it("splits files by the day they were added, keeping their order", () => {
    const groups = groupByDay(filterFiles(FILES, NO_FILTER), now);
    expect(groups.map((g) => [g.label, g.files.map((u) => u.name)])).toEqual([
      ["Today", ["shot-2.png", "shot-1.png"]],
      ["Yesterday", ["spec.pdf"]],
      [dayLabel("2026-10-09", now), ["old-plan.pdf"]],
    ]);
  });

  it("names an older day by its date, with the year only when it isn't this one", () => {
    expect(dayLabel("2026-10-09", now)).toMatch(/October 9/);
    expect(dayLabel("2026-10-09", now)).not.toMatch(/2026/);
    expect(dayLabel("2025-12-31", now)).toMatch(/2025/);
  });
});

describe("originLabel", () => {
  it("says where a file was posted", () => {
    expect(originLabel(FILES[1])).toBe("In the channel");
    expect(originLabel(FILES[2])).toBe("In Fix settings");
    expect(originLabel(FILES[0])).toBe("Saved to memory");
  });
});
