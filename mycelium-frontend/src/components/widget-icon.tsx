// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * A widget's icon: any Lucide icon by its kebab-case name, or one emoji drawn
 * as text. A name Lucide doesn't have, or none, is the default icon. The
 * names the card had before any icon could be named still read as they did,
 * and are drawn at once; any other name loads the icon list
 * (`widget-icon-named.tsx`) when a widget first asks for one.
 */

import dynamic from "next/dynamic";
import { CircleDot, HardDrive, MemoryStick, Type, Upload, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** The card's first five icons, by the names configs already use, and their own. */
const AT_HAND: Record<string, LucideIcon> = {
  memory: MemoryStick,
  "memory-stick": MemoryStick,
  disk: HardDrive,
  "hard-drive": HardDrive,
  upload: Upload,
  ci: CircleDot,
  "circle-dot": CircleDot,
  text: Type,
  type: Type,
};

const NamedIcon = dynamic(() => import("./widget-icon-named"), {
  ssr: false,
  loading: () => <Type className="size-3.5 flex-shrink-0 text-faint" aria-hidden />,
});

const NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function WidgetIcon({ name, className }: { name: string | null; className?: string }) {
  const base = cn("size-3.5 flex-shrink-0", className);
  if (name && !NAME.test(name)) {
    return (
      <span aria-hidden className={cn(base, "grid place-items-center text-[12px] leading-none")}>
        {name}
      </span>
    );
  }
  const Icon = AT_HAND[name ?? "text"];
  if (Icon) return <Icon className={base} aria-hidden />;
  return <NamedIcon name={name!} className={base} />;
}
