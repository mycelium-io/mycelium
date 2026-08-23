// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo } from "react";
import { BookOpen } from "lucide-react";
import { useCommands } from "@/components/keymap-provider";
import { Tooltip } from "@/components/ui/tooltip";
import { DOCS_URL } from "@/lib/install";
import type { PaletteCommand } from "@/lib/commands";

/** The docs site, one icon along from the theme toggle. The header corner is
 *  already where the app keeps the things that are about the app rather than
 *  about the room, and the docs are hosted elsewhere, so this opens in its own
 *  tab rather than taking the workspace with it. */
export function DocsLink() {
  const commands = useMemo<PaletteCommand[]>(
    () => [
      {
        id: "docs.open",
        title: "Open documentation",
        group: "Help",
        keywords: ["docs", "documentation", "guide", "reference", "help"],
        run: () => window.open(DOCS_URL, "_blank", "noreferrer"),
      },
    ],
    [],
  );
  useCommands(commands);

  return (
    <Tooltip content="Documentation" side="bottom">
      <a
        href={DOCS_URL}
        target="_blank"
        rel="noreferrer"
        aria-label="Documentation"
        className="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
      >
        <BookOpen className="size-4" />
      </a>
    </Tooltip>
  );
}
