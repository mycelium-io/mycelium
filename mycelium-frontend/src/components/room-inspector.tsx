// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import {
  Activity,
  Brain,
  PanelRightClose,
  PanelRightOpen,
  Users,
  type LucideIcon,
} from "lucide-react";
import { usePanelRef } from "react-resizable-panels";
import { AgentsPanel } from "@/components/agents-panel";
import { EpisodesRail } from "@/components/episodes-rail";
import { KeyBadge } from "@/components/key-badge";
import { MemoryPanel } from "@/components/memory-panel";
import { ResizableHandle, ResizablePanel } from "@/components/ui/resizable";
import { chordFor, chordKey } from "@/lib/keymap";
import {
  COLLAPSED_THRESHOLD_PX,
  INSPECTOR_PANEL,
  PANEL_INSPECTOR,
  TAB_LABELS_MIN_WIDTH,
} from "@/lib/panel-layout";
import type { FocusTarget } from "@/lib/search";

// Skills aren't a rail: a skill is just a `skills/…` memory, so it shows up in
// the Memory list like any other. No dedicated tab or panel.
export type Tab = "agents" | "episodes" | "memory";

const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "agents", label: "Members", icon: Users },
  { id: "episodes", label: "Episodes", icon: Activity },
  { id: "memory", label: "Memory", icon: Brain },
];

/** "Collapse the rail (\)" — the keybind is spelled out here because `\` isn't
 *  a reveal chord, so KeyBadge can't draw it on the button. Unmodified, so
 *  `chordKey` reads the same on every platform and survives hydration. */
function railToggleTitle(open: boolean): string {
  const chord = chordFor("rail.toggle");
  const suffix = chord ? ` (${chordKey(chord)})` : "";
  return `${open ? "Collapse" : "Expand"} the rail${suffix}`;
}

interface Props {
  roomName: string;
  masId?: string | null;
  /** Optional controlled tab + open state (e.g. driven from the status bar). */
  tab?: Tab;
  onTabChange?: (tab: Tab) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** One-shot request to show the engine invite form (from the palette). */
  engineInvite?: boolean;
  onEngineInviteShown?: () => void;
  /** One item to select, arrived at from search. Only the rail that owns that
   *  kind of row sees it; the others are handed null. */
  focus?: FocusTarget | null;
  onFocusConsumed?: () => void;
  /** Reveal a memory by key in the Memory tab (e.g. a clicked chat wikilink). */
  focusMemory?: { key: string; nonce: number } | null;
}

/**
 * The inspector as a resizable panel: the seam beside it, the panel that holds
 * it, and the wiring that makes the collapse button, the drag, and the `\`
 * keybind three ways of doing the same thing.
 *
 * Open/closed *is* the panel's collapsed state rather than a second flag beside
 * it. That's what lets the button reopen the rail at the width you last dragged
 * it to instead of a constant, and it's why dragging the seam past the minimum
 * shuts the rail rather than jamming against a wall. Double-clicking the seam
 * puts it back to the default width.
 */
export function RoomInspectorPanel({ open: openProp, onOpenChange, ...rest }: Props) {
  const [openInternal, setOpenInternal] = useState(true);
  const open = openProp ?? openInternal;
  const panelRef = usePanelRef();

  const setOpen = useCallback(
    (next: boolean) => {
      if (openProp === undefined) setOpenInternal(next);
      onOpenChange?.(next);
    },
    [openProp, onOpenChange],
  );

  // State → panel. `collapse`/`expand` are no-ops when already in that state,
  // so this settles rather than ping-ponging with `onResize` below.
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    if (open && panel.isCollapsed()) panel.expand();
    else if (!open && !panel.isCollapsed()) panel.collapse();
  }, [open, panelRef]);

  return (
    <>
      <ResizableHandle withHandle />
      <ResizablePanel
        id={PANEL_INSPECTOR}
        panelRef={panelRef}
        collapsible
        collapsedSize={INSPECTOR_PANEL.collapsed}
        defaultSize={INSPECTOR_PANEL.default}
        minSize={INSPECTOR_PANEL.min}
        maxSize={INSPECTOR_PANEL.max}
        groupResizeBehavior="preserve-pixel-size"
        className="flex"
        // Panel → state, so a drag past the minimum reads as "closed" to the
        // status bar and the keybind, and a restored collapsed layout doesn't
        // come back claiming to be open.
        onResize={size => {
          const collapsed = size.inPixels <= COLLAPSED_THRESHOLD_PX;
          if (collapsed === open) setOpen(!collapsed);
        }}
      >
        <RoomInspector {...rest} open={open} onOpenChange={setOpen} />
      </ResizablePanel>
    </>
  );
}

/**
 * How much of the tab strip fits. The rail is draggable down to a width that
 * can't hold three labelled tabs, so below `TAB_LABELS_MIN_WIDTH` they drop to
 * icons alone — the labels move into tooltips and accessible names rather than
 * clipping or wrapping the strip onto a second row.
 *
 * Measured off the rail itself, not the viewport: the rail is the box the tabs
 * have to fit inside, and it changes width without the window doing anything.
 */
function useCompactTabs(ref: RefObject<HTMLElement | null>): boolean {
  const [compact, setCompact] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setCompact(entry.contentRect.width < TAB_LABELS_MIN_WIDTH);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return compact;
}

/** The room's context: agents, episodes, and memory behind one tabbed right rail. */
export function RoomInspector({
  roomName,
  masId,
  tab: tabProp,
  onTabChange,
  open: openProp,
  onOpenChange,
  engineInvite = false,
  onEngineInviteShown,
  focus = null,
  onFocusConsumed,
  focusMemory,
}: Props) {
  const focused = (type: FocusTarget["type"]) => (focus?.type === type ? focus.id : null);
  const [tabInternal, setTabInternal] = useState<Tab>("agents");
  const [openInternal, setOpenInternal] = useState(true);
  const tab = tabProp ?? tabInternal;
  const open = openProp ?? openInternal;
  const setTab = (t: Tab) => { if (tabProp === undefined) setTabInternal(t); onTabChange?.(t); };
  const setOpen = (o: boolean) => { if (openProp === undefined) setOpenInternal(o); onOpenChange?.(o); };

  const railRef = useRef<HTMLElement>(null);
  const compact = useCompactTabs(railRef);

  // Collapsed: a slim strip of the three tab icons; clicking one expands to it.
  if (!open) {
    return (
      <aside className="flex w-full min-w-0 flex-col items-center gap-1 overflow-hidden bg-surface/40 pt-3">
        <button
          onClick={() => setOpen(true)}
          aria-label={railToggleTitle(false)}
          title={railToggleTitle(false)}
          className="flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <PanelRightOpen className="size-[18px]" />
        </button>
        <div className="mt-1 h-px w-5 bg-border" />
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => { setTab(id); setOpen(true); }}
            aria-label={label}
            title={label}
            className={`relative flex size-9 items-center justify-center rounded-lg transition-colors hover:bg-surface hover:text-text ${
              tab === id ? "text-accent" : "text-muted-foreground"
            }`}
          >
            <Icon className="size-[18px]" />
            <KeyBadge action={`rail.${id}`} overlay />
          </button>
        ))}
      </aside>
    );
  }

  return (
    <aside ref={railRef} className="flex w-full min-w-0 flex-col overflow-hidden bg-surface/30">
      <div className="flex h-[48px] flex-shrink-0 items-center gap-1 border-b border-border bg-paper px-2">
        <div className="flex min-w-0 items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                data-tour={`inspector-${id}`}
                onClick={() => setTab(id)}
                aria-label={label}
                title={compact ? label : undefined}
                className={`relative flex items-center gap-1.5 rounded-md py-1 text-label font-medium transition-colors ${
                  compact ? "px-2" : "px-2.5"
                } ${
                  active ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text"
                }`}
              >
                <Icon className="size-3.5 flex-shrink-0" />
                {!compact && label}
                <KeyBadge action={`rail.${id}`} overlay={compact} />
              </button>
            );
          })}
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label={railToggleTitle(true)}
          title={railToggleTitle(true)}
          className="ml-auto flex size-7 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <PanelRightClose className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "agents" && (
          <AgentsPanel
            roomName={roomName}
            engineInvite={engineInvite}
            onEngineInviteShown={onEngineInviteShown}
            focusHandle={focused("agent")}
            onFocusConsumed={onFocusConsumed}
          />
        )}
        {tab === "episodes" && (
          <EpisodesRail
            roomName={roomName}
            focusShortId={focused("episode")}
            onFocusConsumed={onFocusConsumed}
          />
        )}
        {tab === "memory" && (
          <MemoryPanel
            roomName={roomName}
            masId={masId ?? null}
            focusKey={focused("memory")}
            onFocusConsumed={onFocusConsumed}
            focusMemory={focusMemory}
          />
        )}
      </div>
    </aside>
  );
}
