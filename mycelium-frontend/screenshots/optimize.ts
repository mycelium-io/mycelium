// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Lossless PNG optimization with oxipng, compiled to WebAssembly
 * (`@jsquash/oxipng`), so no one needs a system install. The pixels are
 * unchanged; only the encoding gets smaller.
 *
 * `capture.ts` runs every PNG it writes through `optimizePng`. Run as a script,
 * it optimizes PNGs in place, for an image committed some other way:
 *
 *   npm run optimize-png -- ../docs/some-shot.png
 *
 * CI's hygiene job (`scripts/check_file_sizes.py`) fails a PNG that oxipng
 * would still shrink by more than 10%, so an image that skipped this step is
 * caught on its PR.
 */

import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import optimise, { init } from "@jsquash/oxipng/optimise.js";

// Level 4 is oxipng's recommended ceiling: on the docs' screenshots it lands
// within ~2% of zopfli at a twentieth of the time.
const LEVEL = 4;

let ready: Promise<unknown> | undefined;

function load(): Promise<unknown> {
  // The package's glue fetches its wasm by URL, which Node can't do for a
  // file, so hand it the compiled module instead.
  ready ??= (async () => {
    const wasm = createRequire(import.meta.url).resolve("@jsquash/oxipng/codec/pkg/squoosh_oxipng_bg.wasm");
    return init(await WebAssembly.compile(await readFile(wasm)));
  })();
  return ready;
}

/** The same image, losslessly smaller (or the input, if oxipng can't beat it). */
export async function optimizePng(png: Buffer): Promise<Buffer> {
  await load();
  const bytes = new Uint8Array(png.byteLength);
  bytes.set(png);
  const out = Buffer.from(await optimise(bytes.buffer, { level: LEVEL, optimiseAlpha: false }));
  return out.byteLength < png.byteLength ? out : png;
}

async function main(files: string[]): Promise<void> {
  if (files.length === 0) {
    throw new Error("usage: npm run optimize-png -- <file.png> ...");
  }
  let before = 0;
  let after = 0;
  for (const file of files) {
    const png = await readFile(file);
    const out = await optimizePng(png);
    before += png.byteLength;
    after += out.byteLength;
    if (out !== png) await writeFile(file, out);
    const saved = Math.round(100 * (1 - out.byteLength / png.byteLength));
    process.stdout.write(`${file}: ${kib(png.byteLength)} -> ${kib(out.byteLength)} (${saved}% smaller)\n`);
  }
  if (files.length > 1) process.stdout.write(`total: ${kib(before)} -> ${kib(after)}\n`);
}

function kib(n: number): string {
  return `${Math.round(n / 1024)} KiB`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).catch((err) => {
    process.stderr.write(`[optimize-png] failed: ${err?.stack ?? err}\n`);
    process.exit(1);
  });
}
