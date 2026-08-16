// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef } from "react";
import { X } from "lucide-react";
import { bindingsInScope, formatChord, type Binding, type KeyScope } from "@/lib/keymap";

function Keycap({ children }: { children: string }) {
  return (
    <kbd className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-micro text-text">
      {children}
    </kbd>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Scopes live right now — the sheet lists the bindings that would fire. */
  scopes: KeyScope[];
  mac: boolean;
}

function groupBindings(bindings: Binding[]): [string, Binding[]][] {
  const groups = new Map<string, Binding[]>();
  for (const b of bindings) {
    const list = groups.get(b.group) ?? [];
    list.push(b);
    groups.set(b.group, list);
  }
  return [...groups.entries()];
}

/** The `?` overlay: every binding live in the current context, read straight
 *  off the keymap so it can't drift from what the keys actually do. */
export function KeymapCheatsheet({ open, onClose, scopes, mac }: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    // The sheet is modal, so the app's keybinds are inert while it's up; it
    // handles its own dismissal.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "?") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreTo.current?.focus?.();
    };
  }, [open, onClose]);

  const groups = useMemo(() => groupBindings(bindingsInScope(scopes)), [scopes]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px] motion-safe:animate-in motion-safe:fade-in-0"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        tabIndex={-1}
        className="relative flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border bg-elevated shadow-2xl outline-none motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95"
      >
        <header className="flex items-center gap-3 border-b border-border px-5 py-3.5">
          <h2 className="text-ui font-semibold text-text">Keyboard shortcuts</h2>
          <span className="text-micro text-muted-foreground">
            Hold <kbd className="font-sans">{mac ? "⌥" : "Alt"}</kbd>{" "}
            to see each key on the thing it selects. Keys are inert while you&apos;re typing —{" "}
            <kbd className="font-sans">Esc</kbd> returns to command mode.
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="ml-auto flex size-7 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 gap-x-8 gap-y-5 overflow-y-auto p-5 sm:grid-cols-2">
          {groups.map(([group, bindings]) => (
            <section key={group}>
              <h3 className="mb-2 text-micro font-semibold uppercase tracking-wide text-muted-foreground">{group}</h3>
              <dl className="space-y-1">
                {bindings.map((b) => (
                  <div key={b.id} className="flex items-baseline gap-3">
                    <dt className="flex flex-shrink-0 items-baseline gap-1">
                      <Keycap>{formatChord(b.keys[0], mac)}</Keycap>
                      {b.abbreviate ? (
                        <>
                          <span className="text-micro text-faint">…</span>
                          <Keycap>{formatChord(b.keys[b.keys.length - 1], mac)}</Keycap>
                        </>
                      ) : (
                        b.keys.length > 1 && (
                          <span className="text-micro text-faint">or {formatChord(b.keys[1], mac)}</span>
                        )
                      )}
                    </dt>
                    <dd className="min-w-0 text-label text-muted-foreground">{b.label}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
