// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useRef, useState } from "react";
import { ChevronRight, Folder, FolderOpen, Loader2 } from "lucide-react";
import { listRunnerFolders, type Runner, type RunnerFolders } from "@/lib/api";
import { runnerName } from "@/lib/runners";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/** `~` for a home folder, as the Folder field shows paths. */
function tilde(path: string): string {
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

/** The folders from `root` down to `path`, each with the path that opens it. */
export function crumbs(root: string, path: string): { name: string; path: string }[] {
  const out = [{ name: tilde(root), path: root }];
  if (path === root || !path.startsWith(`${root}/`)) return out;
  let at = root;
  for (const part of path.slice(root.length + 1).split("/").filter(Boolean)) {
    at = `${at}/${part}`;
    out.push({ name: part, path: at });
  }
  return out;
}

/** Where to open: the folder typed, when it's inside a root; else the machine's first root. */
function startAt(runner: Runner, typed: string): string | undefined {
  const inside = runner.roots.some((r) => typed === r || typed.startsWith(`${r}/`));
  return inside ? typed : undefined;
}

/**
 * Browse a machine's folders and pick where an agent works.
 *
 * The folders are the runner's, which may not be the computer this browser is
 * on, so the browser's own folder dialog can't do it: each folder opened is
 * listed by the runner (`POST /api/runners/{id}/folders`), only inside its
 * roots, and only folders. `value` is the folder as typed, already expanded
 * to an absolute path; `onPick` gets the absolute path chosen.
 */
export function FolderPicker({
  runner,
  value,
  onPick,
}: {
  runner: Runner;
  value: string;
  onPick: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [listing, setListing] = useState<RunnerFolders | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Only the newest request may answer, however the machine's replies arrive.
  const asked = useRef(0);

  const go = useCallback(
    async (path?: string, fallBackToRoot = false) => {
      const n = ++asked.current;
      setLoading(true);
      setError(null);
      try {
        let got: RunnerFolders;
        try {
          got = await listRunnerFolders(runner.id, path);
        } catch (e) {
          // A typed folder that isn't there (yet) opens at the root instead.
          if (!(fallBackToRoot && path)) throw e;
          got = await listRunnerFolders(runner.id);
        }
        if (n === asked.current) setListing(got);
      } catch (e) {
        if (n !== asked.current) return;
        const message = e instanceof Error ? e.message : String(e);
        setError(
          /doesn't know how to do/.test(message)
            ? `Update Mycelium on ${runnerName(runner)} to browse its folders. You can still type a path.`
            : message,
        );
      } finally {
        if (n === asked.current) setLoading(false);
      }
    },
    [runner],
  );

  // Opened afresh each time, at the folder typed then.
  const openChange = (next: boolean) => {
    setOpen(next);
    if (!next) return;
    setListing(null);
    void go(startAt(runner, value), true);
  };

  const roots = runner.roots;
  const atRoot = listing !== null && listing.path === listing.root;

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger
        aria-label="Browse folders"
        title={`Browse folders on ${runnerName(runner)}`}
        className="flex size-8 flex-shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:border-border2 hover:text-text data-[popup-open]:border-accent data-[popup-open]:text-accent"
      >
        <FolderOpen className="size-4" />
      </PopoverTrigger>
      <PopoverContent side="top" align="end" className="w-96 p-0">
        <div className="space-y-2 border-b border-border px-3 py-2.5">
          {roots.length > 1 && (
            <div className="flex flex-wrap gap-1" role="group" aria-label="Folders agents may work in">
              {roots.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => void go(r)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 font-mono text-micro transition-colors",
                    listing?.root === r
                      ? "border-accent bg-accent/10 text-text"
                      : "border-border text-muted-foreground hover:border-border2 hover:text-text",
                  )}
                >
                  {tilde(r)}
                </button>
              ))}
            </div>
          )}
          <nav aria-label="Folder" className="flex min-w-0 flex-wrap items-center gap-0.5 font-mono text-micro">
            {listing
              ? crumbs(listing.root, listing.path).map((c, i, all) => (
                  <span key={c.path} className="flex min-w-0 items-center gap-0.5">
                    {i > 0 && <ChevronRight className="size-3 flex-shrink-0 text-faint" aria-hidden />}
                    {i === all.length - 1 ? (
                      <span className="truncate text-text" aria-current="location">
                        {c.name}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void go(c.path)}
                        className="truncate rounded px-0.5 text-muted-foreground hover:bg-hairline hover:text-text"
                      >
                        {c.name}
                      </button>
                    )}
                  </span>
                ))
              : <span className="text-faint">{runnerName(runner)}</span>}
          </nav>
        </div>
        <div className="max-h-64 min-h-24 overflow-y-auto p-1">
          {error ? (
            <p role="alert" className="px-2 py-2 text-label text-red">
              {error}
            </p>
          ) : listing === null || (loading && listing.folders.length === 0) ? (
            <p className="flex items-center gap-2 px-2 py-2 text-label text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Looking on {runnerName(runner)}…
            </p>
          ) : listing.folders.length === 0 ? (
            <p className="px-2 py-2 text-label text-muted-foreground">No folders in here.</p>
          ) : (
            <ul className={cn("transition-opacity", loading && "opacity-50")}>
              {listing.folders.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => void go(`${listing.path}/${name}`)}
                    className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-label text-text hover:bg-hairline"
                  >
                    <Folder className="size-3.5 flex-shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{name}</span>
                    <ChevronRight className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
                  </button>
                </li>
              ))}
              {listing.truncated && (
                <li className="px-2 py-1.5 text-micro text-faint">More folders are here than can be listed. Type the path.</li>
              )}
            </ul>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-border px-3 py-2">
          <span className="min-w-0 flex-1 truncate font-mono text-micro text-muted-foreground">
            {listing ? tilde(listing.path) : ""}
          </span>
          {listing && !atRoot && (
            <Button variant="ghost" size="xs" onClick={() => void go(crumbs(listing.root, listing.path).at(-2)?.path)}>
              Up
            </Button>
          )}
          <Button
            size="xs"
            disabled={!listing || loading}
            onClick={() => {
              if (!listing) return;
              onPick(listing.path);
              setOpen(false);
            }}
          >
            Use this folder
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
