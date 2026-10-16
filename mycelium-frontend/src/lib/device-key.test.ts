// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { fingerprint, keyIdOf, normalizeCode, pairingWith, pairProof, signFor } from "@/lib/device-key";
import type { RunnerPairing } from "@/lib/api";

const pairing = (over: Partial<RunnerPairing> = {}): RunnerPairing => ({
  name: "work laptop",
  key: "10e112267b23b604",
  paired_at: "2026-10-01T00:00:00Z",
  expires_at: null,
  folders: [],
  clis: [],
  swarms: false,
  ...over,
});

describe("device-key", () => {
  it("reads a code back the way a person types it", () => {
    expect(normalizeCode("abcd-efgh-jkmo ")).toBe("ABCDEFGHJKM0");
    expect(normalizeCode("i1l1 0000 0000")).toBe("111100000000");
    expect(normalizeCode("ABCD-EFGH")).toBeNull();
    expect(normalizeCode("ABCD-EFGH-JKMU")).toBeNull();
  });

  it("makes the proof the runner checks (`pairing.proof`)", async () => {
    // test_runner.py pins the same value from Python.
    const proof = await pairProof("K7QM4XHD9RWA", "work laptop", "A".repeat(43), "B".repeat(43));
    expect(proof).toBe("zakRBGwNeLR_W1E702hnTIRWyo1daHS8tqBe3QmCZOc");
  });

  it("names a key the way the runner does", async () => {
    // The vector test_runner.py verifies a WebCrypto signature with.
    const id = await keyIdOf(
      "kGLaxTmOR24jd44ln-NWsHpIvRVwmbKQpjAhdVVbNng",
      "4NdlYCR4WCc4s-0SXpeuNflUTHFt2ppIRnbcR5NYDVo",
    );
    expect(id).toBe("10e112267b23b604");
    expect(fingerprint(id)).toBe("10e1 1226 7b23 b604");
  });

  it("finds this device's live pairing on a machine, and only that", () => {
    const runner = { pairings: [pairing(), pairing({ key: "ffffffffffffffff", name: "other" })] };
    expect(pairingWith(runner, "10e112267b23b604")?.name).toBe("work laptop");
    expect(pairingWith(runner, null)).toBeNull();
    expect(pairingWith({ pairings: [pairing({ expires_at: "2020-01-01T00:00:00Z" })] }, "10e112267b23b604")).toBeNull();
  });

  it("signs nothing for a machine with no pairings", async () => {
    const job = { kind: "launch" as const, job: { room: "eng", handle: "a", framework: "claude", cwd: null, worktree: false } };
    expect(await signFor({ id: "m", pairings: [] }, job)).toBeUndefined();
    // No device key here (no IndexedDB): a paired-looking machine still gets no signature.
    expect(await signFor({ id: "m", pairings: [pairing()] }, job)).toBeUndefined();
  });
});
