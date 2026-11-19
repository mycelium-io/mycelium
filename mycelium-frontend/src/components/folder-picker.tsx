// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { FolderOpen } from "lucide-react";
import type { Runner } from "@/lib/api";
import { chooseFolderHere, desktopMachine, useThisMachine } from "@/lib/desktop";

/** Whether `path` is one of `roots` or inside one, with either separator,
 *  since a Windows folder is `C:\code\api`. */
export function insideRoots(path: string, roots: string[]): boolean {
  return roots.some((root) => {
    const base = root.replace(/[\\/]+$/, "");
    return path === root || path === base || path.startsWith(`${base}/`) || path.startsWith(`${base}\\`);
  });
}

/**
 * Pick where an agent works with the system's own folder dialog.
 *
 * Only in the desktop app, on its own hub, for an agent starting on the same
 * machine: a browser can't tell a page a folder's path, and the dialog picks
 * on the machine it opens on. Anywhere else this renders nothing and the path
 * is typed. `value` is the folder as typed, already absolute; `onPick` gets
 * the absolute path chosen, when it's one the machine lets agents start in.
 */
export function FolderPicker({
  runner,
  value,
  onPick,
  iconOnly = false,
}: {
  runner: Runner;
  value: string;
  onPick: (path: string) => void;
  /** Just the folder mark, to sit at the start of the folder field itself. */
  iconOnly?: boolean;
}) {
  const here = useThisMachine();
  const [error, setError] = useState<string | null>(null);
  if (!here || here !== runner.id) return null;

  const choose = async () => {
    setError(null);
    const start = insideRoots(value, runner.roots) ? value : runner.roots[0];
    let picked: string | null;
    try {
      picked = await chooseFolderHere(start);
    } catch {
      setError("The folder dialog didn't open. Type the path instead.");
      return;
    }
    if (!picked) return;
    if (!insideRoots(picked, runner.roots)) {
      setError(`Pick a folder inside ${runner.roots.join(" or ")}.`);
      return;
    }
    onPick(picked);
  };

  return (
    <span className="relative flex-shrink-0">
      <button
        type="button"
        onClick={() => void choose()}
        title={`Choose a folder on this ${desktopMachine()}`}
        aria-label={iconOnly ? "Choose a folder" : undefined}
        className={
          iconOnly
            ? "-ml-1 flex size-6 items-center justify-center rounded text-faint transition-colors hover:bg-hairline hover:text-text"
            : "flex h-8 items-center gap-1.5 rounded-md border border-border px-2 text-label text-muted-foreground transition-colors hover:border-border2 hover:text-text"
        }
      >
        <FolderOpen className={iconOnly ? "size-3.5" : "size-4"} aria-hidden />
        {!iconOnly && "Choose…"}
      </button>
      {error && (
        <p
          role="alert"
          className="absolute right-0 bottom-full mb-1.5 w-64 rounded-md border border-border bg-popover px-2.5 py-1.5 text-micro text-red shadow-md"
        >
          {error}
        </p>
      )}
    </span>
  );
}
