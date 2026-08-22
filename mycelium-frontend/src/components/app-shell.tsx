// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import { Terminal } from "lucide-react";
import { useDefaultLayout } from "react-resizable-panels";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { GlobalSearch, GlobalSearchButton } from "@/components/global-search";
import { CommandPaletteButton, KeymapHelpButton } from "@/components/keymap-provider";
import { InstallModalProvider, useOpenInstallModal } from "@/components/install-modal";
import { MetricsStatusLink } from "@/components/status-items";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  PANEL_ROOMS,
  PANEL_WORKSPACE,
  ROOMS_PANEL,
  SHELL_GROUP_ID,
  WORKSPACE_PANEL,
  layoutStorage,
} from "@/lib/panel-layout";

interface Props {
  /** The open room (highlights its sidebar row); null on the home view. */
  activeRoom?: string | null;
  /** Left side of the top header row: page/room identity. */
  header?: ReactNode;
  /** Right side of the top header row, before the always-present install button. */
  headerRight?: ReactNode;
  /** Left/right slots of the bottom status bar (editor-style). */
  statusLeft?: ReactNode;
  statusRight?: ReactNode;
  children: ReactNode;
}

function InstallCliButton() {
  const openInstallModal = useOpenInstallModal();
  return (
    <Button variant="ghost" size="sm" className="gap-1.5" onClick={openInstallModal}>
      <Terminal className="size-3.5" />
      Install CLI
    </Button>
  );
}

/** The app frame: rooms sidebar, a top header row, workspace, and status bar
 *  (editor-style). The header row is shared by every page rather than each
 *  page drawing its own, so the "Install the CLI" affordance lives in one
 *  place instead of being re-added per page.
 *
 *  The rooms rail is draggable and its width is remembered per browser — long
 *  room names and a wide window pull in opposite directions, and this is the
 *  one rail on every page, so it's the reader's call rather than a constant.
 *  Double-clicking the seam puts it back to the default. */
export function AppShell({
  activeRoom = null,
  header,
  headerRight,
  statusLeft,
  statusRight,
  children,
}: Props) {
  const { defaultLayout, onLayoutChange, onLayoutChanged } = useDefaultLayout({
    id: SHELL_GROUP_ID,
    storage: layoutStorage,
    panelIds: [PANEL_ROOMS, PANEL_WORKSPACE],
  });

  return (
    <GlobalSearch>
      <InstallModalProvider>
        <div
          className="flex h-screen flex-col overflow-hidden bg-bg text-text"
          data-app-shell="ready"
        >
          <ResizablePanelGroup
            className="min-h-0 flex-1"
            defaultLayout={defaultLayout}
            onLayoutChange={onLayoutChange}
            onLayoutChanged={onLayoutChanged}
          >
            <ResizablePanel
              id={PANEL_ROOMS}
              defaultSize={ROOMS_PANEL.default}
              minSize={ROOMS_PANEL.min}
              maxSize={ROOMS_PANEL.max}
              groupResizeBehavior="preserve-pixel-size"
              className="flex"
            >
              <RoomsSidebar activeRoom={activeRoom} />
            </ResizablePanel>

            <ResizableHandle withHandle />

            <ResizablePanel
              id={PANEL_WORKSPACE}
              minSize={WORKSPACE_PANEL.min}
              className="flex min-w-0 flex-col"
            >
              <header className="flex h-[52px] flex-shrink-0 items-center gap-3 border-b border-border bg-surface/50 px-5">
                {header}
                {/* Appearance sits top-right, the corner every app puts it in,
                    rather than crowding the identity row at the other end. */}
                <div className="ml-auto flex flex-shrink-0 items-center gap-3">
                  {headerRight}
                  <InstallCliButton />
                  <ThemeToggle />
                </div>
              </header>
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
            </ResizablePanel>
          </ResizablePanelGroup>
          <footer className="flex h-6 flex-shrink-0 items-center gap-3 border-t border-border bg-surface px-3 text-micro text-muted-foreground">
            {statusLeft}
            <div className="ml-auto flex items-center gap-3">
              {statusRight}
              <MetricsStatusLink />
              <GlobalSearchButton />
              <CommandPaletteButton />
              <KeymapHelpButton />
            </div>
          </footer>
        </div>
      </InstallModalProvider>
    </GlobalSearch>
  );
}
