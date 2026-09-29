// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import {
  Brain,
  PanelRightClose,
  PanelRightOpen,
  Users,
  type LucideIcon,
} from "lucide-react";
import { AgentsPanel } from "@/components/agents-panel";
import { KeyBadge } from "@/components/key-badge";
import { Tooltip } from "@/components/ui/tooltip";
import { MemoryPanel } from "@/components/memory-panel";
import { chordFor, chordKey } from "@/lib/keymap";
import { TAB_LABELS_MIN_WIDTH } from "@/lib/panel-layout";
import type { FocusTarget } from "@/lib/search";

// Skills aren't a rail: a skill is just a `skills/…` memory, so it shows up in
// the Memory list like any other. No dedicated tab or panel.
export type Tab = "agents" | "memory";

const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "agents", label: "Members", icon: Users },
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
  /** Open a memory as a tab in the room, instead of in the Memory rail's drawer. */
  onOpenMemory?: (key: string) => void;
  /** The memory open in the room's tabs, marked in the tree. */
  activeMemoryKey?: string | null;
}

/**
 * How much of the tab strip fits. The rail is draggable down to a width that
 * can't hold the labeled tabs, so below `TAB_LABELS_MIN_WIDTH` they drop to
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

/** The room's context: agents and memory behind one tabbed right rail. */
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
  onOpenMemory,
  activeMemoryKey = null,
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

  // Collapsed: a slim strip of the tab icons; clicking one expands to it.
  if (!open) {
    return (
      <aside className="flex w-full min-w-0 flex-col items-center gap-0.5 overflow-hidden bg-surface/40 pt-1">
        <Tooltip content={railToggleTitle(false)} side="left">
          <button
            onClick={() => setOpen(true)}
            aria-label={railToggleTitle(false)}
            className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <PanelRightOpen className="size-3.5" />
          </button>
        </Tooltip>
        <div className="my-1 h-px w-4 bg-border" />
        {TABS.map(({ id, label, icon: Icon }) => (
          <Tooltip key={id} content={label} side="left">
            <button
              onClick={() => { setTab(id); setOpen(true); }}
              aria-label={label}
              className={`relative flex size-6 items-center justify-center rounded transition-colors hover:bg-hairline hover:text-text ${
                tab === id ? "text-text" : "text-muted-foreground"
              }`}
            >
              <Icon className="size-3.5" />
              <KeyBadge action={`rail.${id}`} overlay />
            </button>
          </Tooltip>
        ))}
      </aside>
    );
  }

  return (
    <aside ref={railRef} className="flex w-full min-w-0 flex-col overflow-hidden bg-surface/30">
      <div className="flex h-8 flex-shrink-0 items-stretch border-b border-border bg-surface pr-1">
        <div className="flex min-w-0 items-stretch">
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            return (
              <Tooltip key={id} content={compact ? label : undefined} side="bottom">
                <button
                  data-tour={`inspector-${id}`}
                  onClick={() => setTab(id)}
                  aria-label={label}
                  className={`relative -mb-px flex items-center gap-1.5 border-r border-border text-label transition-colors ${
                    compact ? "px-2" : "px-3"
                  } ${
                    active ? "bg-bg text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
                  }`}
                >
                  <Icon className="size-3.5 flex-shrink-0" />
                  {!compact && label}
                  <KeyBadge action={`rail.${id}`} overlay={compact} />
                </button>
              </Tooltip>
            );
          })}
        </div>
        <Tooltip content={railToggleTitle(true)} side="bottom">
          <button
            onClick={() => setOpen(false)}
            aria-label={railToggleTitle(true)}
            className="my-auto ml-auto flex size-6 flex-shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <PanelRightClose className="size-3.5" />
          </button>
        </Tooltip>
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
        {tab === "memory" && (
          <MemoryPanel
            roomName={roomName}
            masId={masId ?? null}
            focusKey={focused("memory")}
            onFocusConsumed={onFocusConsumed}
            focusMemory={focusMemory}
            onOpenMemory={onOpenMemory}
            activeKey={activeMemoryKey}
          />
        )}
      </div>
    </aside>
  );
}
