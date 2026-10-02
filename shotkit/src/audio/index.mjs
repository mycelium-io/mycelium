// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * shotkit's sound, as a library: `import { addSound, mixSoundtrack } from "shotkit/audio"`.
 *
 * The one call most callers want is `addSound(video, { bed })`. A project that
 * scores its own bed renders a stereo pair with the primitives here (dsp.mjs)
 * and passes it as `bed`; the clicks, the leveling and the mux stay shotkit's.
 */

export * from "./dsp.mjs";
export * from "./master.mjs";
export * from "./cues.mjs";
export * from "./foley.mjs";
export * from "./io.mjs";
export * from "./soundtrack.mjs";
