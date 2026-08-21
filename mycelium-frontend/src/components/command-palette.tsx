// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { paletteFilter, paletteSections, type PaletteCommand } from "@/lib/commands";
import { eventToChord, formatChord, matchBinding } from "@/lib/keymap";

interface Props {
  open: boolean;
  /** Dismissal — Escape, the backdrop, or ⌘K again. Running a command closes
   *  the palette through `onRun` instead, so the two are told apart. */
  onClose: () => void;
  /** Everything runnable here and now: the keymap's bindings plus whatever the
   *  mounted components have registered. */
  commands: PaletteCommand[];
  recent: string[];
  onRun: (id: string) => void;
  mac: boolean;
}

/** ⌘K: every navigation and action in the app, searchable, one keystroke away.
 *
 *  It is the same vocabulary as the keys — each row that has a chord shows it,
 *  so using the palette teaches the shortcut that would have skipped it. What
 *  the palette adds is reach: the rooms past the ninth, and the actions that
 *  never earned a key of their own.
 *
 *  A single input, no modes. Command-style search over a room's history is a
 *  separate surface; if it ever shares this one it arrives as a prefix on this
 *  query, which is why nothing here parses the text itself — cmdk scores it. */
export function CommandPalette({ open, onClose, commands, recent, onRun, mac }: Props) {
  const [query, setQuery] = useState("");
  const restoreTo = useRef<HTMLElement | null>(null);
  // A command that moves focus (the composer, a dialog) must keep it: restoring
  // only makes sense when the palette was dismissed without running anything.
  const ran = useRef(false);

  useEffect(() => {
    if (!open) return;
    // Reset query and capture the element to restore focus to on close. These
    // must run in an effect because restoreTo reads document.activeElement (a
    // DOM side effect) and ran.current + setQuery reset the palette together.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
    ran.current = false;
    restoreTo.current = document.activeElement as HTMLElement | null;

    // The app's keys are inert behind an open dialog, so the palette handles
    // its own dismissal — including the chord that opened it, as a toggle.
    const onKey = (e: KeyboardEvent) => {
      const closing =
        e.key === "Escape" || matchBinding(eventToChord(e, mac), ["global"])?.id === "palette.open";
      if (!closing) return;
      e.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (!ran.current) restoreTo.current?.focus?.();
    };
  }, [open, onClose, mac]);

  const sections = useMemo(() => paletteSections(commands, recent, query), [commands, recent, query]);
  const filter = useMemo(() => paletteFilter(recent), [recent]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[1px] motion-safe:animate-in motion-safe:fade-in-0"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative flex w-full max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-elevated shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95"
      >
        <Command label="Command palette" loop filter={filter}>
          <CommandInput
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search rooms, panes, actions…"
          />
          <CommandList>
            <CommandEmpty>No matching commands.</CommandEmpty>
            {sections.map(section => (
              <CommandGroup key={section.heading} heading={section.heading}>
                {section.commands.map(command => (
                  <CommandItem
                    key={command.id}
                    value={command.id}
                    keywords={[command.title, command.group, ...(command.keywords ?? [])]}
                    onSelect={() => {
                      ran.current = true;
                      onRun(command.id);
                    }}
                  >
                    <span className="truncate">{command.title}</span>
                    {command.shortcut && (
                      <CommandShortcut>{formatChord(command.shortcut, mac)}</CommandShortcut>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>

        <footer className="flex flex-shrink-0 items-center gap-3 border-t border-border px-4 py-2 text-micro text-muted-foreground">
          <span>
            <kbd className="font-sans">↑↓</kbd> navigate
          </span>
          <span>
            <kbd className="font-sans">↵</kbd> run
          </span>
          <span>
            <kbd className="font-sans">esc</kbd> close
          </span>
        </footer>
      </div>
    </div>
  );
}
