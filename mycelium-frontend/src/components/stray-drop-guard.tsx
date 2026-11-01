// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect } from "react";

/** Whether a drag carries files from outside the page, not a card or text. */
function carriesFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

/**
 * A file dropped anywhere but a drop target does nothing.
 *
 * Without this, a file let go of outside the composer is what the web view
 * opens by default: the browser, and the desktop app with it, replaced the
 * whole app with the dropped file. A drop target (the composer) takes the
 * drag first and cancels it itself, so this only acts on the drags nobody
 * took: it says no drop is allowed there, and cancels the drop if one comes.
 * Mounted once, at the root.
 */
export function StrayDropGuard(): null {
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.defaultPrevented || !carriesFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "none";
    };
    const drop = (e: DragEvent) => {
      if (e.defaultPrevented || !carriesFiles(e)) return;
      e.preventDefault();
    };
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, []);
  return null;
}
