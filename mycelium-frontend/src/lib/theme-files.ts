// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * This machine's theme files, on the app's own server: ~/.mycelium/themes/
 * and ~/.mycelium/theme.json beside it, where `mycelium theme` and agents put
 * them. Only where the desktop app says where the folder is
 * (MYCELIUM_THEMES_DIR); anywhere else there are none.
 *
 * `GET/PUT /api/themes` reads and writes them. `themeFileEvents` says when they
 * change, as the `themes` feed of the app's one held stream
 * (`app/api/stream/route.ts`), so the open app reads them again then and never
 * otherwise.
 */

import { watch, type FSWatcher } from "node:fs";
import path from "node:path";

export function themesFolder(): string | null {
  const dir = process.env.MYCELIUM_THEMES_DIR?.trim();
  return dir ? path.resolve(dir) : null;
}

/** ~/.mycelium/theme.json, beside the themes folder. */
export const pickFile = (dir: string) => path.join(path.dirname(dir), "theme.json");

/** One write is often several file events (a temp file, then a rename). */
const SETTLE_MS = 100;

const CHANGED = "data: {}\n\n";

/**
 * A stream of server-sent events, one each time a theme file or the pick is
 * written, whoever wrote it. It says one at the start too: a change made while
 * nobody was listening was never said, so a feed that (re)opens reads the files
 * once. It carries nothing else; the app reads the themes from GET /api/themes.
 * Ends when `signal` aborts.
 */
export function themeFileEvents(dir: string, signal: AbortSignal): Response {
  const home = path.dirname(dir);
  const folderName = path.basename(dir);
  const pickName = path.basename(pickFile(dir));
  const encoder = new TextEncoder();
  let stop = () => {};

  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      let settle: ReturnType<typeof setTimeout> | undefined;
      let themesWatch: FSWatcher | null = null;
      let homeWatch: FSWatcher | null = null;
      const send = () => {
        try {
          controller.enqueue(encoder.encode(CHANGED));
        } catch {
          stop();
        }
      };
      const changed = () => {
        clearTimeout(settle);
        settle = setTimeout(send, SETTLE_MS);
      };
      // The folder may not be there yet (no theme added), or be removed and
      // made again; it is watched whenever it is there.
      const watchThemes = () => {
        if (themesWatch) return;
        try {
          themesWatch = watch(dir, changed);
          themesWatch.on("error", () => {
            themesWatch?.close();
            themesWatch = null;
          });
        } catch {
          themesWatch = null;
        }
      };
      watchThemes();
      try {
        // theme.json is replaced, not written in place (the CLI writes
        // `.theme.*.json` and renames it), so it is watched through its
        // folder: a watch on the file would end at the first rename.
        homeWatch = watch(home, (_event, name) => {
          const file = name?.toString();
          if (file && file !== folderName && file !== pickName && !file.startsWith(".theme.")) return;
          if (!file || file === folderName) watchThemes();
          changed();
        });
        homeWatch.on("error", () => stop());
      } catch {
        // Nothing to watch it by: the app still reads the themes when it opens.
      }
      stop = () => {
        clearTimeout(settle);
        themesWatch?.close();
        homeWatch?.close();
        themesWatch = homeWatch = null;
        try {
          controller.close();
        } catch {
          // Already closed.
        }
      };
      if (signal.aborted) stop();
      else signal.addEventListener("abort", () => stop(), { once: true });
      send();
    },
    cancel() {
      stop();
    },
  });

  return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
}
