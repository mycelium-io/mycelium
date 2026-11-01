// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The one icon-only button. Its size comes from where it sits, never from the
 * icon inside it: `xs` in the 24px status bar and inline in rows, `sm` in a
 * panel's or a tab strip's header, `md` in the title bar. Every one is quiet
 * until hovered, shares one hover and one pressed look, and must say what it
 * does: the label is its tooltip and its accessible name, with the key that
 * does the same thing beside it when the keymap binds one.
 */

import type { ComponentProps, ReactNode } from "react";
import { Tooltip } from "@/components/ui/tooltip";
import { KbdChord } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";

export type IconButtonSize = "xs" | "sm" | "md";

const SIZE: Record<IconButtonSize, string> = {
  xs: "size-5 rounded [&_svg]:size-3.5",
  sm: "size-6 rounded-md [&_svg]:size-3.5",
  md: "size-7 rounded-md [&_svg]:size-4",
};

export const ICON_BUTTON =
  "inline-flex flex-shrink-0 items-center justify-center text-muted-foreground transition-colors outline-none hover:bg-hairline hover:text-text focus-visible:ring-2 focus-visible:ring-accent/40 disabled:pointer-events-none disabled:opacity-40 aria-pressed:text-text aria-[current=page]:text-text [&_svg]:flex-shrink-0";

export function iconButtonClass(size: IconButtonSize = "sm", className?: string): string {
  return cn(ICON_BUTTON, SIZE[size], className);
}

interface Common {
  /** What it does, as its tooltip and accessible name. */
  label: string;
  size?: IconButtonSize;
  /** A keymap action this button duplicates; its chord shows in the tooltip. */
  action?: string;
  side?: "top" | "bottom" | "left" | "right";
  /** Lit, for a toggle that is on. */
  pressed?: boolean;
  className?: string;
  children: ReactNode;
}

function tip(label: string, action: string | undefined): ReactNode {
  if (!action) return label;
  return (
    <span className="flex items-center gap-1.5">
      {label}
      <KbdChord size="xs" tone="muted" action={action} />
    </span>
  );
}

export function IconButton({
  label,
  size = "sm",
  action,
  side,
  pressed,
  className,
  children,
  ...rest
}: Common & Omit<ComponentProps<"button">, "children" | "aria-label">) {
  return (
    <Tooltip content={tip(label, action)} side={side}>
      <button
        type="button"
        aria-label={label}
        aria-pressed={pressed}
        className={iconButtonClass(size, className)}
        {...rest}
      >
        {children}
      </button>
    </Tooltip>
  );
}

/** The same button, as a link. */
export function IconLink({
  label,
  size = "sm",
  action,
  side,
  className,
  children,
  ...rest
}: Omit<Common, "pressed"> & Omit<ComponentProps<"a">, "children" | "aria-label">) {
  return (
    <Tooltip content={tip(label, action)} side={side}>
      <a aria-label={label} className={iconButtonClass(size, className)} {...rest}>
        {children}
      </a>
    </Tooltip>
  );
}
