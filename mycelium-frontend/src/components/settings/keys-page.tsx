// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Kbd, KbdChord } from "@/components/ui/kbd";
import { useKeyCapture } from "@/components/keymap-provider";
import { useIsMac } from "@/lib/client-hooks";
import { clientSettingHref, useClientSetting } from "@/lib/client-settings";
import { useIsDesktop } from "@/lib/desktop";
import {
  activeKeymap,
  conflictsFor,
  defaultKeys,
  eventToChord,
  FIXED_BINDINGS,
  formatChord,
  isBrowserKept,
  isModifierKey,
  type Binding,
} from "@/lib/keymap";
import { cn } from "@/lib/utils";
import { SettingsPage } from "./settings-ui";

type Filter = "all" | "changed";

interface Pending {
  id: string;
  chord: string;
  clashes: Binding[];
}

function Keys({ binding, mac }: { binding: Binding; mac: boolean }) {
  if (binding.abbreviate) {
    return (
      <span className="flex items-baseline gap-1">
        <KbdChord size="sm" chord={binding.keys[0]} mac={mac} />
        <span className="text-micro text-faint">…</span>
        <KbdChord size="sm" chord={binding.keys[binding.keys.length - 1]} mac={mac} />
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-baseline gap-1">
      {binding.keys.map((k, i) => (
        <span key={k} className="flex items-baseline gap-1">
          {i > 0 && <span className="text-micro text-faint">or</span>}
          <KbdChord size="sm" chord={k} mac={mac} tone={i > 0 ? "muted" : undefined} />
        </span>
      ))}
    </span>
  );
}

/** Every keyboard shortcut, and the person's own keys for any of them. A change
 *  that collides with another action asks first (Swap, or Cancel), so a key
 *  never quietly stops doing what it did. */
export function KeysPage() {
  const mac = useIsMac();
  const desktop = useIsDesktop();
  const captureKeys = useKeyCapture();
  const [overrides, setOverrides] = useClientSetting("keys.overrides");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [recording, setRecording] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);

  const save = (next: Record<string, string[]>) => {
    setOverrides(next);
    setPending(null);
  };
  const setKeys = (id: string, keys: string[]) => {
    const next = { ...overrides };
    if (JSON.stringify(keys) === JSON.stringify(defaultKeys(id))) delete next[id];
    else next[id] = keys;
    return next;
  };

  // While recording, the next key pressed is the new one; Escape stops.
  useEffect(() => {
    if (!recording) return;
    return captureKeys((e) => {
      if (isModifierKey(e.key)) return;
      e.preventDefault();
      if (e.key === "Escape") {
        setRecording(null);
        return;
      }
      const chord = eventToChord(e, mac);
      const clashes = conflictsFor(recording, [chord]);
      setRecording(null);
      if (clashes.length > 0) setPending({ id: recording, chord, clashes });
      else save(setKeys(recording, [chord]));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- save/setKeys read the latest overrides
  }, [recording, captureKeys, mac]);

  // Swap: the action that had the key gets this one's old keys.
  const swap = () => {
    if (!pending) return;
    const mine = activeKeymap().find((b) => b.id === pending.id)?.keys ?? [];
    let next = setKeys(pending.id, [pending.chord]);
    for (const other of pending.clashes) {
      const kept = other.keys.filter((k) => k !== pending.chord);
      next = { ...next, [other.id]: kept.length > 0 ? kept : mine };
      if (JSON.stringify(next[other.id]) === JSON.stringify(defaultKeys(other.id))) delete next[other.id];
    }
    save(next);
  };

  const bindings = activeKeymap();
  const q = query.trim().toLowerCase();
  const shown = useMemo(
    () =>
      bindings.filter((b) => {
        if (filter === "changed" && !overrides[b.id]) return false;
        if (!q) return true;
        const keyText = b.keys.map((k) => formatChord(k, mac).toLowerCase()).join(" ");
        return b.label.toLowerCase().includes(q) || b.group.toLowerCase().includes(q) || keyText.includes(q);
      }),
    [bindings, filter, overrides, q, mac],
  );
  const groups = useMemo(() => {
    const map = new Map<string, Binding[]>();
    for (const b of shown) map.set(b.group, [...(map.get(b.group) ?? []), b]);
    return [...map.entries()];
  }, [shown]);
  const changedCount = Object.keys(overrides).length;

  return (
    <SettingsPage
      title="Keyboard shortcuts"
      scope={desktop ? "Saved in this app on this computer." : "Saved in this browser."}
      actions={
        changedCount > 0 ? (
          <Button variant="outline" size="sm" onClick={() => save({})}>
            Reset all
          </Button>
        ) : undefined
      }
    >
      <div className="mt-5 grid gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-border px-3 py-2 text-micro text-muted-foreground">
          <span className="text-text">One key</span> when no box has focus.
        </div>
        <div className="rounded-lg border border-border px-3 py-2 text-micro text-muted-foreground">
          <Kbd size="xs">{mac ? "⌥" : "Alt"}</Kbd> <span className="text-text">to go somewhere.</span> Hold it to see
          every key.
        </div>
        <div className="rounded-lg border border-border px-3 py-2 text-micro text-muted-foreground">
          <Kbd size="xs">{mac ? "⌘" : "Ctrl"}</Kbd> <span className="text-text">while typing</span>, since letters
          type there.
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by action or key"
          aria-label="Search shortcuts"
          className="h-8 min-w-0 flex-1 rounded-md border border-border bg-bg px-2.5 text-label text-text placeholder:text-faint"
        />
        <div role="radiogroup" aria-label="Show" className="flex rounded-md border border-border p-0.5">
          {(["all", "changed"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                "rounded px-2.5 py-1 text-label",
                filter === f ? "bg-surface text-text" : "text-muted-foreground hover:text-text",
              )}
            >
              {f === "all" ? "All" : `Changed ${changedCount}`}
            </button>
          ))}
        </div>
      </div>

      {groups.length === 0 && <p className="mt-6 text-label text-muted-foreground">No shortcut matches that.</p>}

      {groups.map(([group, list]) => (
        <section key={group} className="mt-6">
          <h2 className="mb-1 text-micro font-semibold uppercase tracking-wide text-faint">{group}</h2>
          <div className="divide-y divide-border rounded-xl border border-border">
            {list.map((b) => {
              const changed = Boolean(overrides[b.id]);
              const fixed = FIXED_BINDINGS.has(b.id);
              const kept = !desktop && b.keys.some(isBrowserKept);
              return (
                <div key={b.id} id={`keys.${b.id}`} className="scroll-mt-24 px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                    <div className="flex min-w-0 flex-1 basis-56 items-center gap-2 text-label text-text">
                      {changed && <span aria-label="Changed" className="size-1.5 rounded-full bg-accent" />}
                      {b.label}
                    </div>
                    {recording === b.id ? (
                      <span className="rounded-md border border-accent px-2 py-0.5 text-micro text-accent">
                        Press the new key… <span className="text-faint">Esc to stop</span>
                      </span>
                    ) : (
                      <Keys binding={b} mac={mac} />
                    )}
                    <div className="flex w-36 justify-end gap-2">
                      {changed && (
                        <button
                          type="button"
                          onClick={() => save(setKeys(b.id, defaultKeys(b.id)))}
                          className="text-micro text-muted-foreground hover:text-text"
                          title={`Default: ${defaultKeys(b.id).map((k) => formatChord(k, mac)).join(" or ")}`}
                        >
                          Reset
                        </button>
                      )}
                      {!fixed && (
                        <button
                          type="button"
                          onClick={() => {
                            setPending(null);
                            setRecording(b.id);
                          }}
                          className="text-micro text-accent hover:underline"
                        >
                          Change
                        </button>
                      )}
                    </div>
                  </div>
                  {kept && (
                    <p className="mt-1 text-micro text-yellow">
                      The browser keeps {formatChord(b.keys.find(isBrowserKept)!, mac)} for itself, so it only works in
                      the desktop app.
                    </p>
                  )}
                  {pending?.id === b.id && (
                    <div
                      role="alertdialog"
                      aria-label="Shortcut already in use"
                      className="mt-2 rounded-lg border border-yellow/40 bg-yellow/5 px-3 py-2"
                    >
                      <p className="text-micro text-text">
                        <KbdChord size="xs" chord={pending.chord} mac={mac} /> is already used for{" "}
                        {pending.clashes.map((c) => c.label).join(" and ")}.
                      </p>
                      <div className="mt-1.5 flex gap-2">
                        <button
                          type="button"
                          onClick={swap}
                          className="rounded-md bg-accent px-2 py-0.5 text-micro font-medium text-accent-fg"
                        >
                          Swap them
                        </button>
                        <button
                          type="button"
                          onClick={() => setPending(null)}
                          className="rounded-md border border-border px-2 py-0.5 text-micro text-text hover:bg-surface"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      <section className="mt-6">
        <h2 className="mb-1 text-micro font-semibold uppercase tracking-wide text-faint">Messages</h2>
        <div className="rounded-xl border border-border px-4 py-2.5 text-label text-text">
          Send a message
          <Link href={clientSettingHref("general.send")} className="ml-2 text-micro text-accent hover:underline">
            Set in General
          </Link>
        </div>
      </section>
    </SettingsPage>
  );
}
