// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Where each click and keystroke falls in a finished video.
 *
 * A take notes them as it records, by the frame they happen on (the pump's
 * count of frames written, so a sped-up stretch is already folded in), and
 * writes them beside the video as `<video>.sounds.json`:
 *
 *   { "fps": 30, "events": [
 *       { "t": 1.233, "kind": "click" },
 *       { "t": 2.4, "kind": "key", "key": "Enter" },
 *       { "t": 3.1, "t1": 4.7, "kind": "type", "chars": 28 } ] }
 *
 * `t` is seconds into the video, title cards included. A sound pass reads this
 * rather than guessing from the picture.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";

/** The cue file that sits beside a video. */
export const cuesPath = (video) => `${video}.sounds.json`;

/**
 * Write a take's cues beside its video.
 * @param {string} out the video's path
 * @param {{beat:number, end?:number, kind:string, [k:string]:unknown}[]} sounds by take frame
 * @param {number} fps
 * @param {number} offset frames before the take's first one (an intro card)
 */
export function writeCues(out, sounds, fps, offset = 0) {
  const at = (beat) => Number(((offset + beat) / fps).toFixed(3));
  const events = sounds.map(({ beat, end, ...rest }) => ({
    t: at(beat),
    ...(typeof end === "number" ? { t1: at(end) } : {}),
    ...rest,
  }));
  writeFileSync(cuesPath(out), JSON.stringify({ fps, events }, null, 1));
}

/**
 * Read a video's cues, or none when it has no cue file.
 * @returns {{t:number, t1?:number, kind:string, chars?:number, key?:string}[]}
 */
export function readCues(video) {
  const path = cuesPath(video);
  if (!existsSync(path)) return [];
  const parsed = JSON.parse(readFileSync(path, "utf8"));
  if (!Array.isArray(parsed?.events)) throw new Error(`${path} has no events array`);
  return parsed.events;
}
