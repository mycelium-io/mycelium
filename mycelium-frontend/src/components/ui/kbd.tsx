// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { useIsMac } from "@/lib/client-hooks";
import { chordFor, formatChord } from "@/lib/keymap";
import { cn } from "@/lib/utils";

/** One keycap language for the whole app. Every surface that names a key —
 *  the cheatsheet, the palettes' shortcut column and their footers, the
 *  composer hint, the status rail — draws it through this, so a key reads the
 *  same wherever it appears and no surface can quietly go back to plain text.
 *
 *  Mono, because a key is a glyph you press rather than a word you read. The
 *  cap is sized by where it sits, not by emphasis: `xs` is the one that fits
 *  the 24px status rail, `sm` is the default for palettes and hint rows, `md`
 *  for the cheatsheet's own two-column list. */
const kbdVariants = cva(
  "inline-flex flex-shrink-0 select-none items-center justify-center rounded border font-mono font-medium leading-none",
  {
    variants: {
      size: {
        xs: "h-4 min-w-4 gap-0.5 px-1 text-[10px]",
        sm: "h-5 min-w-5 gap-0.5 px-1.5 text-[11px]",
        md: "h-[22px] min-w-[22px] gap-1 px-1.5 text-micro",
      },
      tone: {
        /** The cap as an object: a raised key on the surface ladder. */
        default: "border-border bg-surface text-text",
        /** A cap inside already-quiet copy — a palette footer, a hint row. */
        muted: "border-border bg-surface text-muted-foreground",
      },
    },
    defaultVariants: { size: "sm", tone: "default" },
  },
);

type KbdProps = ComponentProps<"kbd"> & VariantProps<typeof kbdVariants>;

/** A literal key, spelled by the caller: `<Kbd>Esc</Kbd>`, `<Kbd>↵</Kbd>`. */
export function Kbd({ className, size, tone, ...props }: KbdProps) {
  return <kbd data-slot="kbd" className={cn(kbdVariants({ size, tone }), className)} {...props} />;
}

interface ChordProps extends Omit<KbdProps, "children"> {
  /** A chord in the keymap's notation ("mod+k", "alt+c", "?"). */
  chord?: string;
  /** An action id, for the chord the keymap currently binds it to. */
  action?: string;
  /** Platform override; defaults to what the browser reports. Call sites that
   *  already carry `mac` (the palettes take it as a prop) pass it through so
   *  one render can't disagree with itself about ⌘ versus Ctrl. */
  mac?: boolean;
}

/** The cap for a chord, spelled for the platform: ⌘K on a Mac, Ctrl+K
 *  elsewhere. Renders nothing when the action has no binding, so a call site
 *  can name an action without first proving the keymap still binds it. */
export function KbdChord({ chord, action, mac, ...props }: ChordProps) {
  const detected = useIsMac();
  const resolved = chord ?? (action ? chordFor(action) : undefined);
  if (!resolved) return null;
  return <Kbd {...props}>{formatChord(resolved, mac ?? detected)}</Kbd>;
}

export { kbdVariants };
