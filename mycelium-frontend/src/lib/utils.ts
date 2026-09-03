// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

/** tailwind-merge decides which of two `text-*` classes wins by knowing which
 *  are sizes and which are colors. It knows Tailwind's own scale, and this app
 *  replaced it (`text-label`, `text-micro`, … in globals.css) — so without this
 *  it reads every custom size as a color, and `cn("text-label text-muted-
 *  foreground")` silently drops the size, leaving the browser default 16px.
 *  Told the five names, size and color stop colliding. */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["micro", "label", "body", "ui", "display"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
