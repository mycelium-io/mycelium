// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Reading notifications aloud, one at a time. Each message is said a sentence
// at a time through the hub's speech server, the next sentence fetched while
// the current one plays. Messages that arrive while one is being read wait
// their turn, up to `QUEUE_CAP`; past that they're counted and said as "and N
// more in the bell" at the end. Nothing is said while a mic is open, here or in
// another tab: reading waits, and a sentence the mic interrupts is said again
// once it's off. Framework-agnostic, so the queue is tested without rendering;
// `notifications-provider.tsx` wires it to the hub, the speakers and the bell.

import { excerptLength, sentencesOf, type Block } from "@/lib/speakable";

/** Messages waiting behind the one being read, past which they're counted. */
export const QUEUE_CAP = 3;

/** How long the popover stays after a message read only in part, so "Read
 *  all" can still be pressed. */
export const LINGER_MS = 8_000;

/** How long a failure stays on the popover before the next message. */
export const ERROR_MS = 4_000;

export interface ReadItem {
  id: string;
  /** Who said it. Empty for the closing "more in the bell" line. */
  sender: string;
  /** The task or room it was said in. */
  where: string;
  /** Where clicking the popover goes. */
  href: string | null;
  blocks: Block[];
}

export type ReaderStatus = "idle" | "speaking" | "held" | "lingering" | "failed";

export interface ReaderState {
  item: ReadItem | null;
  status: ReaderStatus;
  /** The sentence being said, as an index into the item's sentences; -1 is
   *  the line naming who and where, null between sentences. */
  at: number | null;
  /** How many of the item's sentences are read: its start, or all after "Read all". */
  end: number;
  total: number;
  /** Messages waiting behind this one, and those past the cap. */
  waiting: number;
  more: number;
  error: string | null;
}

export interface ReaderDeps {
  /** The audio for one sentence. */
  fetch(text: string, signal: AbortSignal): Promise<ArrayBuffer>;
  /** Play it; resolves when it ends, or rejects when `signal` aborts. */
  play(audio: ArrayBuffer, signal: AbortSignal): Promise<void>;
  micOpen(): Promise<boolean>;
  onMicChange(listener: () => void): () => void;
  onChange(state: ReaderState): void;
  /** A timer; tests pass a controllable one. */
  sleep?(ms: number, signal: AbortSignal): Promise<void>;
}

export const IDLE: ReaderState = {
  item: null,
  status: "idle",
  at: null,
  end: 0,
  total: 0,
  waiting: 0,
  more: 0,
  error: null,
};

class Aborted extends Error {}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Aborted());
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new Aborted());
    });
  });
}

/** The line said before a message: who, and where. */
export function introOf(item: ReadItem): string {
  if (!item.sender) return "";
  return item.where ? `${item.sender}, in ${item.where}.` : `${item.sender}.`;
}

/** The closing line for messages past the cap. */
export function moreItem(count: number): ReadItem {
  const text = `And ${count} more in the bell.`;
  return {
    id: `more:${count}`,
    sender: "",
    where: "",
    href: null,
    blocks: [{ kind: "paragraph", sentences: [{ show: text, say: text }] }],
  };
}

export interface Reader {
  /** Read this message once the ones before it are done. */
  enqueue(item: ReadItem): void;
  /** Stop reading and drop everything waiting. */
  stop(): void;
  /** Read the rest of the current message. */
  readAll(): void;
  /** While the pointer is on the popover, a message read in part stays. */
  keepOpen(open: boolean): void;
  state(): ReaderState;
  dispose(): void;
}

export function createReader(deps: ReaderDeps): Reader {
  const sleep = deps.sleep ?? wait;
  let state: ReaderState = IDLE;
  const queue: ReadItem[] = [];
  let more = 0;
  let running = false;
  /** Aborts everything the current run is doing: fetches, playback, waits. */
  let run = new AbortController();
  /** Aborts the sentence playing, when a mic opens over it. */
  let sentence: AbortController | null = null;
  let hovering = false;
  let wake: (() => void) | null = null;

  const set = (patch: Partial<ReaderState>) => {
    state = { ...state, ...patch, waiting: queue.length, more };
    deps.onChange(state);
  };
  const poke = () => {
    wake?.();
    wake = null;
  };

  const unsubscribe = deps.onMicChange(() => {
    // A mic opening stops the sentence at once; closing it lets reading go on.
    void deps.micOpen().then((open) => {
      if (open) sentence?.abort();
      poke();
    });
  });

  /** Resolves once no mic is open, showing the wait meanwhile. */
  async function untilMicClosed(signal: AbortSignal): Promise<void> {
    while (await deps.micOpen()) {
      if (signal.aborted) throw new Aborted();
      set({ status: "held", at: null });
      await new Promise<void>((resolve, reject) => {
        wake = resolve;
        signal.addEventListener("abort", () => reject(new Aborted()), { once: true });
      });
    }
    if (signal.aborted) throw new Aborted();
  }

  async function read(item: ReadItem, signal: AbortSignal): Promise<void> {
    const sentences = sentencesOf(item.blocks);
    const intro = introOf(item);
    // Index -1 is the intro, then each sentence of the message.
    const texts = (i: number) => (i < 0 ? intro : sentences[i].say);
    const audio = new Map<number, Promise<ArrayBuffer>>();
    const fetchAt = (i: number) => {
      if (!audio.has(i)) {
        const pending = deps.fetch(texts(i), signal);
        pending.catch(() => {});
        audio.set(i, pending);
      }
      return audio.get(i)!;
    };
    const first = intro ? -1 : 0;
    set({ item, status: "speaking", at: null, end: excerptLength(item.blocks), total: sentences.length, error: null });

    for (let i = first; i < state.end; ) {
      await untilMicClosed(signal);
      const sound = await fetchAt(i);
      if (i + 1 < state.end) fetchAt(i + 1);
      // The mic may have opened while that was on its way.
      if (await deps.micOpen()) continue;
      const playing = new AbortController();
      sentence = playing;
      const stopPlaying = () => playing.abort();
      signal.addEventListener("abort", stopPlaying, { once: true });
      set({ status: "speaking", at: i });
      try {
        await deps.play(sound, playing.signal);
      } catch (err) {
        if (signal.aborted) throw new Aborted();
        // A mic opened over it: say this sentence again once it's off.
        if (playing.signal.aborted) continue;
        throw err;
      } finally {
        signal.removeEventListener("abort", stopPlaying);
        sentence = null;
      }
      i++;
      // Read only in part: stay a while, so "Read all" can be pressed.
      if (i >= state.end && state.end < state.total) {
        set({ status: "lingering", at: null });
        await linger(signal);
        if (i < state.end) fetchAt(i);
      }
    }
  }

  /** Wait out `LINGER_MS`, longer while the pointer is on the popover, or
   *  until "Read all" is pressed. */
  async function linger(signal: AbortSignal): Promise<void> {
    const end = state.end;
    let left = LINGER_MS;
    while (left > 0 && state.end === end) {
      const step = Math.min(left, 500);
      await Promise.race([
        sleep(step, signal),
        new Promise<void>((resolve) => (wake = resolve)),
      ]);
      if (signal.aborted) throw new Aborted();
      if (!hovering) left -= step;
    }
  }

  async function loop(): Promise<void> {
    if (running) return;
    running = true;
    const signal = run.signal;
    try {
      while (!signal.aborted) {
        const item = queue.shift() ?? (more > 0 ? moreItem(more) : null);
        if (!item) break;
        if (item.id.startsWith("more:")) more = 0;
        try {
          await read(item, signal);
        } catch (err) {
          if (err instanceof Aborted || signal.aborted) break;
          set({ status: "failed", at: null, error: err instanceof Error ? err.message : String(err) });
          try {
            await sleep(ERROR_MS, signal);
          } catch {
            break;
          }
        }
      }
    } finally {
      // A run that `stop` replaced leaves the new one alone.
      if (signal === run.signal) {
        running = false;
        set({ ...IDLE });
      }
    }
  }

  return {
    enqueue(item) {
      if (!item.blocks.length) return;
      if (state.item?.id === item.id || queue.some((q) => q.id === item.id)) return;
      if (queue.length >= QUEUE_CAP) more++;
      else queue.push(item);
      if (running) set({});
      else void loop();
    },
    stop() {
      queue.length = 0;
      more = 0;
      run.abort();
      run = new AbortController();
      running = false;
      poke();
      set({ ...IDLE });
    },
    readAll() {
      if (!state.item || state.end >= state.total) return;
      set({ end: state.total, status: state.status === "lingering" ? "speaking" : state.status });
      poke();
    },
    keepOpen(open) {
      hovering = open;
    },
    state: () => state,
    dispose() {
      unsubscribe();
      queue.length = 0;
      run.abort();
    },
  };
}
