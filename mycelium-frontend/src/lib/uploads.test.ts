// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  acceptAttribute,
  extensionOf,
  formatBytes,
  parseDelimited,
  refusalFor,
  textViewFor,
  uploadKeysIn,
  withoutTrailingUploadLinks,
} from "@/lib/uploads";

describe("uploadKeysIn", () => {
  it("finds each upload link once, in order", () => {
    const text = "here [[uploads/a.png]] and [[uploads/b.pdf]], again [[uploads/a.png]]";
    expect(uploadKeysIn(text)).toEqual(["uploads/a.png", "uploads/b.pdf"]);
  });

  it("drops a label or anchor but keeps the key", () => {
    expect(uploadKeysIn("[[uploads/plan.pdf|the plan]]")).toEqual(["uploads/plan.pdf"]);
  });

  it("ignores other memories, transclusions and links inside code", () => {
    const text = "[[context/x]] ![[uploads/a.png]] `[[uploads/b.png]]`\n```\n[[uploads/c.png]]\n```";
    expect(uploadKeysIn(text)).toEqual([]);
  });
});

describe("withoutTrailingUploadLinks", () => {
  it("drops the line of links the composer adds", () => {
    expect(withoutTrailingUploadLinks("the mockups\n\n[[uploads/a.png]] [[uploads/b.pdf]]")).toBe("the mockups");
    expect(withoutTrailingUploadLinks("[[uploads/a.png]]")).toBe("");
  });

  it("keeps a link written into the prose", () => {
    const text = "see [[uploads/a.png]] for the layout";
    expect(withoutTrailingUploadLinks(text)).toBe(text);
    expect(withoutTrailingUploadLinks("ends with [[uploads/a.png]]")).toBe("ends with [[uploads/a.png]]");
  });
});

describe("refusalFor", () => {
  const accepted = ["png", "pdf", "md"];

  it("takes a file the hub previews", () => {
    expect(refusalFor({ name: "Plan.PDF", size: 10 }, accepted, 100)).toBeNull();
  });

  it("names a type the hub won't take", () => {
    expect(refusalFor({ name: "tool.exe", size: 10 }, accepted, 100)).toMatch(/\.exe files/);
    expect(refusalFor({ name: "README", size: 10 }, accepted, 100)).toMatch(/without an extension/);
  });

  it("refuses a file over the cap or an empty one", () => {
    expect(refusalFor({ name: "a.png", size: 101 }, accepted, 100)).toMatch(/Larger than/);
    expect(refusalFor({ name: "a.png", size: 0 }, accepted, 100)).toMatch(/empty/);
  });

  it("leaves it to the hub before the hub's list has loaded", () => {
    expect(refusalFor({ name: "tool.exe", size: 10 }, [], 0)).toBeNull();
  });
});

describe("helpers", () => {
  it("reads an extension the way the hub does", () => {
    expect(extensionOf("a.tar.GZ")).toBe("gz");
    expect(extensionOf("README")).toBe("");
  });

  it("builds a picker's accept list", () => {
    expect(acceptAttribute(["png", "pdf"])).toBe(".png,.pdf");
    expect(acceptAttribute([])).toBeUndefined();
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(25 * 1024 * 1024)).toBe("25 MB");
  });

  it("picks a text view by extension", () => {
    expect(textViewFor("notes.md")).toBe("markdown");
    expect(textViewFor("data.tsv")).toBe("table");
    expect(textViewFor("main.py")).toBe("source");
  });

  it("parses quoted CSV", () => {
    expect(parseDelimited('a,b\n"x, y","say ""hi"""\r\n3,4', ",")).toEqual([
      ["a", "b"],
      ["x, y", 'say "hi"'],
      ["3", "4"],
    ]);
  });
});
