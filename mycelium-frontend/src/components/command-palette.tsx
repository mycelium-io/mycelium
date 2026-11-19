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
import { Kbd } from "@/components/ui/kbd";
import { MODAL_BACKDROP, ModalDialog } from "@/components/ui/modal-dialog";

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
  const dialogRef = useRef<HTMLDialogElement>(null);
  // Running a command closes the dialog itself, and that close isn't a
  // dismissal.
  const ran = useRef(false);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
    ran.current = false;

    // The app's keys are inert behind an open dialog, so the chord that opened
    // the palette is handled here, as a toggle. The dialog handles Escape.
    const onKey = (e: KeyboardEvent) => {
      if (matchBinding(eventToChord(e, mac), ["global"])?.id !== "palette.open") return;
      e.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, mac]);

  const sections = useMemo(() => paletteSections(commands, recent, query), [commands, recent, query]);
  const filter = useMemo(() => paletteFilter(recent), [recent]);

  if (!open) return null;

  return (
    <ModalDialog
      ref={dialogRef}
      onClose={() => {
        if (!ran.current) onClose();
      }}
      aria-label="Command palette"
      className={`mx-auto mt-[12vh] w-[calc(100%-3rem)] max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-elevated shadow-2xl open:flex motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 ${MODAL_BACKDROP}`}
    >
      <Command label="Command palette" loop filter={filter}>
        <CommandInput
          autoFocus
          data-autofocus
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
                    // Closed before the command runs, so the page is no
                    // longer inert and a command can move focus into it.
                    ran.current = true;
                    dialogRef.current?.close();
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
        <span className="flex items-center gap-1.5">
          <Kbd size="xs" tone="muted">↑↓</Kbd> navigate
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd size="xs" tone="muted">↵</Kbd> run
        </span>
        <span className="flex items-center gap-1.5">
          <Kbd size="xs" tone="muted">Esc</Kbd> close
        </span>
      </footer>
    </ModalDialog>
  );
}
