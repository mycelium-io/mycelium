// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Download, PanelLeft, Terminal } from "lucide-react";
import { TitleBar } from "@/components/title-bar";
import { Tooltip } from "@/components/ui/tooltip";
import { KbdChord } from "@/components/ui/kbd";
import { useDefaultLayout } from "react-resizable-panels";
import { RoomsSidebar } from "@/components/rooms-sidebar";
import { GlobalSearch, GlobalSearchButton } from "@/components/global-search";
import { CommandPaletteButton, KeymapHelpButton } from "@/components/keymap-provider";
import { InstallModalProvider, useOpenInstallModal } from "@/components/install-modal";
import { DocsLink } from "@/components/docs-link";
import { DMG_URL, useIsDesktop } from "@/lib/desktop";
import { useIsMac } from "@/lib/client-hooks";
import { GlobalStatusItems, MachinesStatusLink, MetricsStatusLink } from "@/components/status-items";
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
  /** The page's name in the title bar, when it isn't a room's. */
  title?: string;
  /** The title bar's breadcrumb after the hub, in place of the room's name. */
  header?: ReactNode;
  /** The title bar's right side, before the app-wide buttons. */
  headerRight?: ReactNode;
  /** Left/right slots of the bottom status bar (editor-style). */
  statusLeft?: ReactNode;
  statusRight?: ReactNode;
  children: ReactNode;
}

/**
 * In a browser on a Mac, says the app exists: someone sent a link lands here
 * with no idea there is more, and the app is what starts agents on their own
 * machine. Hidden inside the app, and on other systems, which it doesn't run on.
 */
function GetMacAppButton() {
  const desktop = useIsDesktop();
  const mac = useIsMac();
  if (desktop || !mac) return null;
  return (
    <Tooltip content="Mycelium for Mac starts your coding agents on this computer and adds them to a room">
      <a
        href={DMG_URL}
        className="flex h-7 items-center gap-1.5 rounded-md px-2 text-label text-accent transition-colors hover:bg-accent-soft"
      >
        <Download className="size-3.5" />
        <span className="hidden sm:inline">Get the Mac app</span>
      </a>
    </Tooltip>
  );
}

/** Hidden inside the Mac app, which puts the CLI on this Mac's PATH itself. */
function InstallCliButton() {
  const openInstallModal = useOpenInstallModal();
  if (useIsDesktop()) return null;
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
/** A status-bar icon that shows or hides a dock, lit while the dock is open. */
function DockToggle({
  label,
  action,
  active,
  onClick,
  children,
}: {
  label: string;
  action: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip content={<>{label} <KbdChord size="xs" tone="muted" action={action} /></>} side="top">
      <button
        type="button"
        aria-label={label}
        aria-pressed={active}
        onClick={onClick}
        className={`flex size-5 flex-shrink-0 items-center justify-center rounded transition-colors hover:bg-hairline hover:text-text ${active ? "text-text" : ""}`}
      >
        {children}
      </button>
    </Tooltip>
  );
}

export function AppShell({
  activeRoom = null,
  title,
  header,
  headerRight,
  statusLeft,
  statusRight,
  children,
}: Props) {
  // Where you are, after the hub in the title bar: what the page names itself,
  // else the room it belongs to, else its title.
  const crumb =
    header ??
    (activeRoom ? (
      <Link
        href={`/room/${encodeURIComponent(activeRoom)}`}
        className="truncate rounded-md px-1.5 py-1 font-medium transition-colors hover:bg-hairline"
      >
        {activeRoom}
      </Link>
    ) : title ? (
      <span className="truncate px-1.5 font-medium">{title}</span>
    ) : null);
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
          <TitleBar
            crumb={crumb}
            right={
              <>
                {headerRight}
                <GetMacAppButton />
                <InstallCliButton />
                <DocsLink />
                <ThemeToggle />
              </>
            }
          />
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
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </div>
          {/* One line, always. Its cells are short but there are a lot of them,
              and a bar that wraps to three rows on a phone eats the workspace
              it is supposed to annotate — so it scrolls sideways instead, and
              the cells that only name a keyboard drop out where there is no
              keyboard to name.

              Three zones, read left to right as near to far: where agents run
              (the docks and this person's machines), what the page is showing
              (`statusLeft`, e.g. the room's connection and counts), then the
              hub as a whole and the keys. Every value carries a word saying
              what it is; the keys are caps alone, named in their tooltips. */}
          <footer className="flex h-6 flex-shrink-0 items-center gap-3 overflow-x-auto border-t border-border bg-surface px-2 text-micro whitespace-nowrap text-muted-foreground [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <DockToggle
              label={roomsOpen ? "Hide rooms" : "Show rooms"}
              action="rooms.toggle"
              active={roomsOpen}
              onClick={() => setRoomsOpen(open => !open)}
            >
              <PanelLeft className="size-3.5" />
            </DockToggle>
            <MachinesStatusLink />
            {statusLeft && (
              <>
                <span aria-hidden className="h-3 w-px flex-shrink-0 bg-border" />
                {statusLeft}
              </>
            )}
            <div className="ml-auto flex flex-shrink-0 items-center gap-3">
              {statusRight}
              <GlobalStatusItems />
              <MetricsStatusLink />
              <span aria-hidden className="hidden h-3 w-px flex-shrink-0 bg-border sm:block" />
              <div className="flex items-center gap-1 xl:gap-2.5">
                <GlobalSearchButton />
                <CommandPaletteButton />
                <KeymapHelpButton />
              </div>
            </div>
          </footer>
        </div>
      </InstallModalProvider>
    </GlobalSearch>
  );
}
