// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { GlobalSearch, GlobalSearchButton } from "@/components/global-search";
import { CommandPaletteButton, KeymapHelpButton } from "@/components/keymap-provider";

interface Props {
  /** The open room (highlights its sidebar row); null on the home view. */
  activeRoom?: string | null;
  /** Left/right slots of the bottom status bar (editor-style). */
  statusLeft?: ReactNode;
  statusRight?: ReactNode;
  children: ReactNode;
}

/** The app frame: rooms sidebar, workspace, and status bar (editor-style). */
export function AppShell({ activeRoom = null, statusLeft, statusRight, children }: Props) {
  return (
    <GlobalSearch>
      <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
        <div className="flex min-h-0 flex-1">
          <RoomsSidebar activeRoom={activeRoom} />
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</div>
        </div>
        <footer className="flex h-6 flex-shrink-0 items-center gap-3 border-t border-border bg-surface px-3 text-micro text-muted-foreground">
          {statusLeft}
          <div className="ml-auto flex items-center gap-3">
            {statusRight}
            <GlobalSearchButton />
            <CommandPaletteButton />
            <KeymapHelpButton />
          </div>
        </footer>
      </div>
    </GlobalSearch>
  );
}
