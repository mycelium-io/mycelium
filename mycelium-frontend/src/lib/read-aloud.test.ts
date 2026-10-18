// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { createReader, LINGER_MS, QUEUE_CAP, type ReaderState, type ReadItem } from "./read-aloud";
import { speakable } from "./speakable";

/** A reader over fake speakers: each `play` waits until the test finishes it. */
function harness() {
  const plays: { text: string; done: () => void; signal: AbortSignal }[] = [];
  const sleeps: { ms: number; resolve: () => void }[] = [];
  const micListeners = new Set<() => void>();
  const failing = new Set<string>();
  let mic = false;
  const states: ReaderState[] = [];
  const reader = createReader({
    fetch: async (text) => {
      if (failing.has(text)) throw new Error("The speech server answered 500.");
      return new TextEncoder().encode(text).buffer as ArrayBuffer;
    },
    play: (audio, signal) =>
      new Promise<void>((resolve, reject) => {
        plays.push({ text: new TextDecoder().decode(audio), done: resolve, signal });
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
    micOpen: async () => mic,
    onMicChange: (listener) => {
      micListeners.add(listener);
      return () => micListeners.delete(listener);
    },
    onChange: (state) => states.push(state),
    sleep: (ms, signal) =>
      new Promise<void>((resolve, reject) => {
        sleeps.push({ ms, resolve });
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  });
  const settle = async () => {
    for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0));
  };
  const live = () => plays.filter((p) => !p.signal.aborted);
  return {
    reader,
    plays,
    sleeps,
    failing,
    settle,
    state: () => reader.state(),
    /** What's playing now. */
    now: () => live().at(-1)?.text ?? null,
    /** Let the sentence playing end, and the reader move on. */
    async finish() {
      await settle();
      const playing = live().at(-1);
      if (playing) {
        playing.done();
        plays.splice(plays.indexOf(playing), 1);
      }
      await settle();
    },
    /** Play every sentence through to the end. */
    async finishAll(limit = 50) {
      const heard: string[] = [];
      for (let i = 0; i < limit; i++) {
        await settle();
        const playing = live().at(-1);
        if (!playing || heard.length && plays.indexOf(playing) < plays.length - 1) break;
        heard.push(playing.text);
        playing.done();
        plays.splice(plays.indexOf(playing), 1);
      }
      await settle();
      return heard;
    },
    async setMic(open: boolean) {
      mic = open;
      for (const l of micListeners) l();
      await settle();
    },
  };
}

function item(id: string, md: string, sender = "julia", where = "Speed up the board"): ReadItem {
  return { id, sender, where, href: `/room/x?focus=message:${id}`, blocks: speakable(md) };
}

describe("createReader", () => {
  it("says who and where, then the message, then goes quiet", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "Can you look? It's slow."));
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "Can you look?", "It's slow."]);
    expect(h.state().status).toBe("idle");
    expect(h.state().item).toBeNull();
  });

  it("lights the sentence being said", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "One. Two."));
    await h.settle();
    expect(h.state()).toMatchObject({ status: "speaking", at: -1, end: 2, total: 2 });
    await h.finish();
    expect(h.state().at).toBe(0);
    await h.finish();
    expect(h.state().at).toBe(1);
  });

  it("reads messages one at a time, in order", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "First."));
    h.reader.enqueue(item("b", "Second.", "coder", "the room"));
    await h.settle();
    expect(h.state().waiting).toBe(1);
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "First.", "coder, in the room.", "Second."]);
  });

  it("caps the queue and says how many more are in the bell", async () => {
    const h = harness();
    for (let i = 0; i < QUEUE_CAP + 3; i++) h.reader.enqueue(item(`m${i}`, `Message ${i}.`));
    await h.settle();
    expect(h.state()).toMatchObject({ waiting: QUEUE_CAP, more: 2 });
    const heard = await h.finishAll();
    expect(heard.filter((t) => t.startsWith("Message"))).toHaveLength(QUEUE_CAP + 1);
    expect(heard.at(-1)).toBe("And 2 more in the bell.");
  });

  it("ignores a message it already has", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "Once."));
    h.reader.enqueue(item("a", "Once."));
    await h.settle();
    expect(h.state().waiting).toBe(0);
  });

  it("stops at once and drops what's waiting", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "One. Two."));
    h.reader.enqueue(item("b", "Next."));
    await h.settle();
    h.reader.stop();
    await h.settle();
    expect(h.plays[0].signal.aborted).toBe(true);
    expect(h.state()).toMatchObject({ status: "idle", item: null, waiting: 0 });
    // A message after a stop is read as usual.
    h.reader.enqueue(item("c", "After."));
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "After."]);
  });

  it("waits while a mic is open, and starts when it's off", async () => {
    const h = harness();
    await h.setMic(true);
    h.reader.enqueue(item("a", "Hello."));
    await h.settle();
    expect(h.state().status).toBe("held");
    expect(h.now()).toBeNull();
    await h.setMic(false);
    expect(h.now()).toBe("julia, in Speed up the board.");
  });

  it("reads the whole message, with no stop, when the person asked for that", async () => {
    const h = harness();
    h.reader.enqueue({ ...item("a", "The start.\n\nThe rest. And more."), whole: true });
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "The start.", "The rest.", "And more."]);
    expect(h.state().status).toBe("idle");
  });

  it("stops the sentence a mic opens over and says it again after", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "One. Two."));
    await h.finish();
    expect(h.now()).toBe("One.");
    await h.setMic(true);
    expect(h.now()).toBeNull();
    expect(h.state().status).toBe("held");
    await h.setMic(false);
    expect(h.now()).toBe("One.");
  });

  it("reads the start of a long message, then the rest on Read all", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "The start.\n\nThe rest. And more."));
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "The start."]);
    expect(h.state()).toMatchObject({ status: "lingering", end: 1, total: 3 });
    h.reader.readAll();
    expect(await h.finishAll()).toEqual(["The rest.", "And more."]);
    expect(h.state().status).toBe("idle");
  });

  it("closes a message read in part after a while, longer while hovered", async () => {
    const h = harness();
    h.reader.enqueue(item("a", "The start.\n\nThe rest."));
    await h.finishAll();
    h.reader.keepOpen(true);
    for (let i = 0; i < 30; i++) {
      h.sleeps.shift()?.resolve();
      await h.settle();
    }
    expect(h.state().status).toBe("lingering");
    h.reader.keepOpen(false);
    for (let i = 0; i < LINGER_MS / 500 + 2; i++) {
      h.sleeps.shift()?.resolve();
      await h.settle();
    }
    expect(h.state().status).toBe("idle");
  });

  it("says why it couldn't read a message, then goes on", async () => {
    const h = harness();
    h.failing.add("Broken.");
    h.reader.enqueue(item("a", "Broken."));
    h.reader.enqueue(item("b", "Fine."));
    await h.finish();
    await h.settle();
    expect(h.state()).toMatchObject({ status: "failed", error: "The speech server answered 500." });
    h.sleeps.shift()?.resolve();
    expect(await h.finishAll()).toEqual(["julia, in Speed up the board.", "Fine."]);
  });
});
