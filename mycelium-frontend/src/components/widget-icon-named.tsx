// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Any Lucide icon by its kebab-case name, for a widget that names one. Kept in
 * a file of its own and loaded only then (`widget-icon.tsx`), since the list of
 * every name is too big to ship with every page; each icon loads on its own.
 */

import { Type } from "lucide-react";
import { DynamicIcon, iconNames, type IconName } from "lucide-react/dynamic";

const KNOWN = new Set<string>(iconNames);

export default function NamedIcon({ name, className }: { name: string; className: string }) {
  if (!KNOWN.has(name)) return <Type className={className} aria-hidden />;
  return (
    <DynamicIcon
      name={name as IconName}
      className={className}
      aria-hidden
      fallback={() => <Type className={className} aria-hidden />}
    />
  );
}
