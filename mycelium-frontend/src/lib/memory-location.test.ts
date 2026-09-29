// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { cleanFolder, folderChoices, joinKey, keyProblem, slugify, treeSlice } from "@/lib/memory-location";

describe("slugify", () => {
  it("turns a title into a key segment", () => {
    expect(slugify("Refund policy for double charges")).toBe("refund-policy-for-double-charges");
  });

  it("drops accents and punctuation, and trims the dashes they leave", () => {
    expect(slugify("  Café: what's next?  ")).toBe("cafe-what-s-next");
  });

  it("keeps a long title to 60 characters without a trailing dash", () => {
    const slug = slugify("word ".repeat(30));
    expect(slug.length).toBeLessThanOrEqual(60);
    expect(slug.endsWith("-")).toBe(false);
  });
});

describe("keys", () => {
  it("joins a folder and a name, cleaning stray slashes", () => {
    expect(cleanFolder(" /Decisions//db/ ")).toBe("decisions/db");
    expect(joinKey("decisions//", "Postgres")).toBe("decisions/postgres");
    expect(joinKey("", "notes")).toBe("notes");
  });

  it("says why a key can't be used", () => {
    expect(keyProblem("")).toBe("Give it a name.");
    expect(keyProblem("context/goals")).toBeNull();
    expect(keyProblem("context/My Goals")).toMatch(/lowercase/);
    expect(keyProblem("context/../etc")).toMatch(/empty/);
    expect(keyProblem("x".repeat(513))).toMatch(/too long/);
  });
});

describe("folderChoices", () => {
  it("offers the room's folders busiest first, then the standard ones, never agents or log", () => {
    const keys = ["work/a", "work/b", "research/x", "agents/sam/notes", "log/episodes/1"];
    expect(folderChoices(keys)).toEqual(["work", "research", "context", "decisions", "procedures", "status", "skills"]);
  });
});

describe("treeSlice", () => {
  const keys = ["decisions/db", "decisions/auth/tokens", "decisions/cache", "context/goals"];

  it("draws the folder a new memory lands in and what sits beside it", () => {
    const slice = treeSlice(keys, "decisions/queue");
    expect(slice.path).toEqual(["decisions"]);
    expect(slice.existing).toEqual([true]);
    expect(slice.folders).toEqual(["auth"]);
    expect(slice.files).toEqual(["cache", "db"]);
    expect(slice.name).toBe("queue");
    expect(slice.exists).toBe(false);
  });

  it("marks folders that don't exist yet", () => {
    const slice = treeSlice(keys, "decisions/infra/queue");
    expect(slice.existing).toEqual([true, false]);
    expect(slice.files).toEqual([]);
  });

  it("says when the key is taken, and doesn't list it twice", () => {
    const slice = treeSlice(keys, "decisions/db");
    expect(slice.exists).toBe(true);
    expect(slice.files).toEqual(["cache"]);
  });

  it("counts what it leaves out", () => {
    const many = Array.from({ length: 8 }, (_, i) => `context/m${i}`);
    const slice = treeSlice(many, "context/new", 5);
    expect(slice.files).toHaveLength(5);
    expect(slice.moreFiles).toBe(3);
  });
});
