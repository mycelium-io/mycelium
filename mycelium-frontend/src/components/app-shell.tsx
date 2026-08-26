// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, type ReactNode } from "react";
import { Terminal } from "lucide-react";
import { useDefaultLayout } from "react-resizable-panels";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { GlobalSearch, GlobalSearchButton } from "@/components/global-search";
import { CommandPaletteButton, KeymapHelpButton } from "@/components/keymap-provider";
import { InstallModalProvider, useOpenInstallModal } from "@/components/install-modal";
import { DocsLink } from "@/components/docs-link";
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
  ROOMS_FOLD_WIDTH,
  SHELL_PANEL_IDS,
  ROOMS_PANEL,
  SHELL_GROUP_ID,
  WORKSPACE_PANEL,
  layoutStorage,
} from "@/lib/panel-layout";
import { useCollapsibleRail } from "@/lib/use-collapsible-rail";
import { useSheetLayout } from "@/lib/use-viewport";
import { RailSheet } from "@/components/rail-sheet";
import { useKeyAction } from "@/components/keymap-provider";

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
    <Button variant="ghost" size="sm" className="gap-1.5" onClick={openInstallModal} aria-label="Install CLI">
      <Terminal className="size-3.5" />
      <span className="hidden sm:inline">Install CLI</span>
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
 *  Double-clicking the seam puts it back to the default, and on a window too
 *  narrow to hold the rail and the workspace at once it folds itself down to a
 *  strip of room monograms until there's room for names again. */
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
    panelIds: SHELL_PANEL_IDS,
  });

  const [roomsOpen, setRoomsOpen] = useState(true);
  const { panelRef, size, onResize } = useCollapsibleRail({
    foldWidth: ROOMS_FOLD_WIDTH,
    defaultWidth: ROOMS_PANEL.default,
    open: roomsOpen,
    onOpenChange: setRoomsOpen,
  });
  useKeyAction("rooms.toggle", () => setRoomsOpen(open => !open));

  // Too narrow for a split: the rail leaves the group and becomes a sheet over
  // the workspace, and its strip stays put so it is still one tap away.
  const sheetLayout = useSheetLayout();
  const railInPanel = roomsOpen && !sheetLayout;

  return (
    <GlobalSearch>
      <InstallModalProvider>
        <div
          className="flex h-screen flex-col overflow-hidden bg-bg text-text"
          data-app-shell="ready"
        >
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {/* Folded, the rail is a plain strip beside the group rather than a
                panel inside it. A panel that isn't there can't be squeezed, and
                comes back at the width it left at — where a panel *told* to
                collapse is at the mercy of a group still solving for the window
                it had a frame ago. Under the sheet layout the strip is what the
                rail always is, with the sheet drawn over the workspace beside
                it. */}
            {!railInPanel && (
              <div className="flex w-12 flex-none border-r border-border">
                <RoomsSidebar
                  activeRoom={activeRoom}
                  collapsed
                  // A toggle rather than "expand": while the sheet is open the
                  // strip is still on screen behind it, and the control that
                  // opened it is the one a reader reaches for to put it away.
                  onCollapsedChange={() => setRoomsOpen(open => !open)}
                />
              </div>
            )}
            <RailSheet
              open={sheetLayout && roomsOpen}
              onClose={() => setRoomsOpen(false)}
              side="left"
              label="Rooms"
            >
              <RoomsSidebar activeRoom={activeRoom} onCollapsedChange={() => setRoomsOpen(false)} />
            </RailSheet>
            <ResizablePanelGroup
              className="min-h-0 flex-1"
              defaultLayout={defaultLayout}
              // Only while both panels are here: a one-panel layout saved over
              // the split would be the rail's remembered width, gone.
              onLayoutChange={railInPanel ? onLayoutChange : undefined}
              onLayoutChanged={railInPanel ? onLayoutChanged : undefined}
            >
              {railInPanel && (
                <>
                  <ResizablePanel
                    id={PANEL_ROOMS}
                    panelRef={panelRef}
                    collapsible
                    collapsedSize={ROOMS_PANEL.collapsed}
                    defaultSize={size}
                    minSize={ROOMS_PANEL.min}
                    maxSize={ROOMS_PANEL.max}
                    groupResizeBehavior="preserve-pixel-size"
                    className="flex"
                    onResize={onResize}
                  >
                    <RoomsSidebar
                      activeRoom={activeRoom}
                      onCollapsedChange={next => setRoomsOpen(!next)}
                    />
                  </ResizablePanel>

                  <ResizableHandle withHandle />
                </>
              )}

              <ResizablePanel
                id={PANEL_WORKSPACE}
                minSize={WORKSPACE_PANEL.min}
                className="flex min-w-0 flex-col"
              >
                <header className="flex h-[52px] flex-shrink-0 items-center gap-2 border-b border-border bg-surface/50 px-3 sm:gap-3 sm:px-5">
                  {header}
                  {/* Appearance sits top-right, the corner every app puts it in,
                      rather than crowding the identity row at the other end. */}
                  <div className="ml-auto flex flex-shrink-0 items-center gap-1 sm:gap-3">
                    {headerRight}
                    <InstallCliButton />
                    <DocsLink />
                    <ThemeToggle />
                  </div>
                </header>
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </div>
          {/* One line, always. Its cells are short but there are a lot of them,
              and a bar that wraps to three rows on a phone eats the workspace
              it is supposed to annotate — so it scrolls sideways instead, and
              the cells that only name a keyboard drop out where there is no
              keyboard to name. */}
          <footer className="flex h-6 flex-shrink-0 items-center gap-3 overflow-x-auto border-t border-border bg-surface px-3 text-micro whitespace-nowrap text-muted-foreground [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {statusLeft}
            <div className="ml-auto flex flex-shrink-0 items-center gap-3">
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
