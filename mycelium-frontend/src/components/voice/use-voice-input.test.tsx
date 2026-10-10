// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWRTestCache } from "@/test/swr";

const sent: { sid: string; samples: number; final: boolean }[] = [];
const replies: { texts: string[]; speaking: boolean; ready?: boolean }[] = [];
const closed: string[] = [];

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  fetchVoiceStatus: async () => ({ state: "ready", detail: "", language: "en", sample_rate: 16000, model: "m" }),
  sendVoiceChunk: async (sid: string, pcm: Int16Array, final = false) => {
    sent.push({ sid, samples: pcm.length, final });
    return replies.shift() ?? { texts: [], speaking: false };
  },
  closeVoiceSession: async (sid: string) => {
    closed.push(sid);
  },
}));

import { useVoiceInput } from "@/components/voice/use-voice-input";

// A browser's audio, minus the audio: the worklet's port is ours to post on.
let port: { onmessage: ((e: MessageEvent<Float32Array>) => void) | null };
const track = { stop: vi.fn() };

class FakeContext {
  sampleRate = 48000;
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }
  close = vi.fn(async () => {});
}

class FakeNode {
  port = { onmessage: null };
  constructor() {
    port = this.port;
  }
  connect = vi.fn();
  disconnect = vi.fn();
}

/** Ten milliseconds of 48 kHz audio from the mic. */
function record(blocks = 1) {
  for (let i = 0; i < blocks; i++) port.onmessage?.({ data: new Float32Array(480).fill(0.2) } as MessageEvent<Float32Array>);
}

beforeEach(() => {
  sent.length = 0;
  replies.length = 0;
  closed.length = 0;
  vi.stubGlobal("AudioContext", FakeContext);
  vi.stubGlobal("AudioWorkletNode", FakeNode);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [track] })) },
  });
  URL.createObjectURL = vi.fn(() => "blob:worklet");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function setup() {
  const heard: string[] = [];
  const errors: string[] = [];
  const hook = renderHook(() => useVoiceInput((t) => heard.push(t), (m) => errors.push(m)), { wrapper: SWRTestCache });
  return { hook, heard, errors };
}

describe("useVoiceInput", () => {
  it("is offered once the hub says it can transcribe", async () => {
    const { hook } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    expect(hook.result.current.state).toBe("off");
  });

  it("stays on, sends what it records at 16 kHz, and hands back what was said", async () => {
    const { hook, heard } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    await act(() => hook.result.current.toggle());
    expect(hook.result.current.state).toBe("listening");
    // The session opens at once with an empty chunk.
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ samples: 0, final: false });

    replies.push({ texts: ["Add Apple Pay to checkout."], speaking: false });
    act(() => record(3));
    await waitFor(() => expect(sent).toHaveLength(2), { timeout: 2000 });
    expect(sent[1].samples).toBe(480); // 30 ms at 48 kHz is 480 samples at 16 kHz
    await waitFor(() => expect(heard).toEqual(["Add Apple Pay to checkout."]));
    // A pause didn't stop it.
    expect(hook.result.current.state).toBe("listening");
    expect(sent.every((s) => s.sid === sent[0].sid)).toBe(true);
  });

  it("sends what's left when it's turned off, and lets go of the mic", async () => {
    const { hook, heard } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    await act(() => hook.result.current.toggle());
    await waitFor(() => expect(sent).toHaveLength(1));
    act(() => record(2));
    replies.push({ texts: ["the last words"], speaking: false });
    await act(() => hook.result.current.toggle());
    expect(hook.result.current.state).toBe("off");
    expect(sent.at(-1)).toMatchObject({ final: true });
    expect(track.stop).toHaveBeenCalled();
    await waitFor(() => expect(heard).toContain("the last words"));
  });

  it("while the hub loads its model, only asks, and keeps the audio until it's ready", async () => {
    const { hook } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    // The opening ask and the next one land while the model loads.
    replies.push({ texts: [], speaking: false, ready: false }, { texts: [], speaking: false, ready: false });
    await act(() => hook.result.current.toggle());
    await waitFor(() => expect(sent).toHaveLength(1));
    act(() => record(3));
    await waitFor(() => expect(sent).toHaveLength(2), { timeout: 2000 });
    // Asking again carries no audio: it waits here rather than going up each tick.
    expect(sent[1].samples).toBe(0);
    await waitFor(() => expect(hook.result.current.warming).toBe(true));

    // The third ask finds it ready; the audio held meanwhile goes on the next tick.
    act(() => record(3));
    await waitFor(() => expect(sent).toHaveLength(4), { timeout: 3000 });
    expect(sent[2].samples).toBe(0);
    expect(sent[3].samples).toBe(960);
    await waitFor(() => expect(hook.result.current.warming).toBe(false));
  });

  it("says why when the mic is blocked", async () => {
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new DOMException("denied", "NotAllowedError"),
    );
    const { hook, errors } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    await act(() => hook.result.current.toggle());
    expect(hook.result.current.state).toBe("off");
    expect(errors[0]).toMatch(/blocked/);
    expect(sent).toHaveLength(0);
  });

  it("closes the session without transcribing when the composer goes away", async () => {
    const { hook } = setup();
    await waitFor(() => expect(hook.result.current.available).toBe(true));
    await act(() => hook.result.current.toggle());
    await waitFor(() => expect(sent).toHaveLength(1));
    hook.unmount();
    expect(closed).toEqual([sent[0].sid]);
    expect(sent.some((s) => s.final)).toBe(false);
  });
});
