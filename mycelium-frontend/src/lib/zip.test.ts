// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { crc32, distinctNames, zipStored } from "@/lib/zip";

const bytes = (s: string) => new TextEncoder().encode(s);

/** The entries a zip's central directory lists: name, size and where each starts. */
function readDirectory(buf: ArrayBuffer): { name: string; size: number; crc: number; data: string }[] {
  const view = new DataView(buf);
  const end = buf.byteLength - 22;
  expect(view.getUint32(end, true)).toBe(0x06054b50);
  const count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  const out = [];
  for (let i = 0; i < count; i++) {
    expect(view.getUint32(at, true)).toBe(0x02014b50);
    const crc = view.getUint32(at + 16, true);
    const size = view.getUint32(at + 24, true);
    const nameLen = view.getUint16(at + 28, true);
    const local = view.getUint32(at + 42, true);
    const name = new TextDecoder().decode(new Uint8Array(buf, at + 46, nameLen));
    // The file's own header, then its bytes.
    expect(view.getUint32(local, true)).toBe(0x04034b50);
    const localNameLen = view.getUint16(local + 26, true);
    const data = new TextDecoder().decode(new Uint8Array(buf, local + 30 + localNameLen, size));
    out.push({ name, size, crc, data });
    at += 46 + nameLen;
  }
  return out;
}

describe("zipStored", () => {
  it("writes each file whole, under its own name, with its checksum", async () => {
    const blob = zipStored([
      { name: "notes.md", data: bytes("# Refunds\n") },
      { name: "café menu.txt", data: bytes("croissant") },
    ]);
    expect(blob.type).toBe("application/zip");
    const files = readDirectory(await blob.arrayBuffer());
    expect(files.map((f) => [f.name, f.data])).toEqual([
      ["notes.md", "# Refunds\n"],
      ["café menu.txt", "croissant"],
    ]);
    expect(files[0].crc).toBe(crc32(bytes("# Refunds\n")));
  });
});

describe("crc32", () => {
  it("matches the standard check value", () => {
    expect(crc32(bytes("123456789"))).toBe(0xcbf43926);
  });
});

describe("distinctNames", () => {
  it("keeps two files with the same name apart", () => {
    expect(distinctNames(["a.png", "b.png", "a.png", "A.png"])).toEqual(["a.png", "b.png", "a (2).png", "A (3).png"]);
  });

  it("steps past a numbered name that was already given", () => {
    expect(distinctNames(["a (2).png", "a.png", "a.png"])).toEqual(["a (2).png", "a.png", "a (3).png"]);
  });

  it("numbers a name with no extension at its end", () => {
    expect(distinctNames(["README", "README"])).toEqual(["README", "README (2)"]);
  });
});
