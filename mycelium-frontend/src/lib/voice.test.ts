// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  appRefusesMic,
  appendHeard,
  concatPcm,
  downsample,
  micErrorMessage,
  newVoiceSessionId,
  toPcm16,
} from "@/lib/voice";

describe("downsample", () => {
  it("averages 48 kHz down to 16 kHz, three samples to one", () => {
    const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48000, 16000);
    expect(Array.from(out)).toEqual([expect.closeTo(0.3), 1]);
  });

  it("handles a rate that isn't a whole multiple", () => {
    expect(downsample(new Float32Array(441), 44100, 16000)).toHaveLength(160);
  });

  it("passes audio at or below the target through", () => {
    const input = new Float32Array([0.5]);
    expect(downsample(input, 16000, 16000)).toBe(input);
  });
});

describe("toPcm16", () => {
  it("scales to 16 bits and clips", () => {
    expect(Array.from(toPcm16(new Float32Array([0, 1, -1, 2, -2])))).toEqual([0, 32767, -32768, 32767, -32768]);
  });

  it("joins chunks in order", () => {
    expect(Array.from(concatPcm([new Int16Array([1, 2]), new Int16Array([3])]))).toEqual([1, 2, 3]);
  });
});

describe("appendHeard", () => {
  it("starts an empty draft with what was said", () => {
    expect(appendHeard("", " Add Apple Pay. ")).toBe("Add Apple Pay.");
    expect(appendHeard("  ", "hi")).toBe("hi");
  });

  it("adds to the end with one space", () => {
    expect(appendHeard("First thing.", "Second thing.")).toBe("First thing. Second thing.");
    expect(appendHeard("Line one\n", "line two")).toBe("Line one\nline two");
  });

  it("leaves the draft alone for silence", () => {
    expect(appendHeard("keep", "  ")).toBe("keep");
  });
});

describe("newVoiceSessionId", () => {
  it("is 32 hex characters, fresh each time", () => {
    const a = newVoiceSessionId();
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(newVoiceSessionId()).not.toBe(a);
  });
});

describe("appRefusesMic", () => {
  it("is false in a browser, wherever the hub is", () => {
    expect(appRefusesMic("hub.example.com", false)).toBe(false);
  });

  it("in the Mac app, allows only its own hub on this machine", () => {
    expect(appRefusesMic("127.0.0.1", true)).toBe(false);
    expect(appRefusesMic("localhost", true)).toBe(false);
    expect(appRefusesMic("hub.example.com", true)).toBe(true);
  });
});

describe("micErrorMessage", () => {
  it("says a blocked mic plainly", () => {
    expect(micErrorMessage(new DOMException("denied", "NotAllowedError"))).toMatch(/blocked/);
    expect(micErrorMessage(new DOMException("none", "NotFoundError"))).toMatch(/no microphone/);
  });
});
