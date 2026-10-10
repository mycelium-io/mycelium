// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  PanelRightClose,
  PanelRightOpen,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useDefaultLayout } from "react-resizable-panels";
import { AgentsPanel } from "@/components/agents-panel";
import { KeyBadge } from "@/components/key-badge";
import { Tooltip } from "@/components/ui/tooltip";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { iconButtonClass } from "@/components/ui/icon-button";
import { MemoryPanel } from "@/components/memory-panel";
import { chordFor, chordKey } from "@/lib/keymap";
import { layoutStorage } from "@/lib/panel-layout";
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
  /** Changes on every ask to show `tab`, so a folded section opens even when
   *  it is already the one named. */
  reveal?: number;
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
  /** Open a memory as a tab in the room, where every memory is read. */
  onOpenMemory: (key: string) => void;
  /** The memory open in the room's tabs, marked in the tree. */
  activeMemoryKey?: string | null;
}

/** A section's header is as tall as the room's tab strip, so the two line up
 *  across the top. An open section is never shorter than `SECTION_MIN`. */
const SECTION_HEADER = 32;
const SECTION_MIN = 120;
const RAIL_GROUP_ID = "mycelium:rail";
const FOLDED_KEY = "mycelium:rail:folded";

function readFolded(): Record<Tab, boolean> {
  try {
    const saved = JSON.parse(layoutStorage.getItem(FOLDED_KEY) ?? "null") as Partial<Record<Tab, boolean>> | null;
    return { agents: saved?.agents === true, memory: saved?.memory === true };
  } catch {
    return { agents: false, memory: false };
  }
}

/** The room's context: members and memory, stacked in one right rail, as an
 *  accordion: each section folds to its header on its own, both can, and while
 *  both are open the seam between them drags. */
export function RoomInspector({
  roomName,
  masId,
  tab: tabProp,
  reveal = 0,
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

  // While both sections are open the seam between them drags, and their split
  // is remembered in this browser, like the room's own. What is folded is
  // remembered too, read once mounted so the server's render matches.
  const { defaultLayout, onLayoutChange, onLayoutChanged } = useDefaultLayout({
    id: RAIL_GROUP_ID,
    storage: layoutStorage,
    panelIds: TABS.map((t) => t.id),
  });
  const [folded, setFolded] = useState<Record<Tab, boolean>>({ agents: false, memory: false });
  const foldedLoaded = useRef(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser storage, read after hydration
    setFolded(readFolded());
    foldedLoaded.current = true;
  }, []);
  useEffect(() => {
    if (foldedLoaded.current) layoutStorage.setItem(FOLDED_KEY, JSON.stringify(folded));
  }, [folded]);
  // Folding is the reader's own choice and asks for nothing: it never moves
  // `tab`, so it can't trip the reveal below and spring back open.
  const toggleSection = (id: Tab) => setFolded((prev) => ({ ...prev, [id]: !prev[id] }));

  // Asked to show a section (its key, the status bar, search, the collapsed
  // strip): open the one asked for, however it was left. Only an ask does
  // this. Mounting is not one, so a section folded and saved stays folded on
  // the next load, and `reveal`/`asked` change on every ask, so asking for
  // the section already named still opens it.
  const [asked, setAsked] = useState(0);
  useEffect(() => {
    if (!open || reveal + asked === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- an ask from outside opens the section
    setFolded((prev) => (prev[tab] ? { ...prev, [tab]: false } : prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs per ask, not when the tab is merely named
  }, [reveal, asked]);

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
              onClick={() => { setTab(id); setAsked(n => n + 1); setOpen(true); }}
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

  const body: Record<Tab, ReactNode> = {
    agents: (
      <AgentsPanel
        roomName={roomName}
        onOpenMemory={onOpenMemory}
        engineInvite={engineInvite}
        onEngineInviteShown={onEngineInviteShown}
        focusHandle={focused("agent")}
        onFocusConsumed={onFocusConsumed}
      />
    ),
    memory: (
      <MemoryPanel
        roomName={roomName}
        masId={masId ?? null}
        focusKey={focused("memory")}
        onFocusConsumed={onFocusConsumed}
        focusMemory={focusMemory}
        onOpenMemory={onOpenMemory}
        activeKey={activeMemoryKey}
      />
    ),
  };

  const header = (id: Tab, label: string, Icon: LucideIcon, i: number) => (
    <div
      className="flex flex-shrink-0 items-center gap-1 border-b border-border bg-surface pl-1 pr-1"
      style={{ height: SECTION_HEADER }}
    >
      <button
        type="button"
        data-tour={`inspector-${id}`}
        onClick={() => toggleSection(id)}
        aria-expanded={!folded[id]}
        aria-label={`${folded[id] ? "Expand" : "Collapse"} ${label}`}
        className="group flex h-full min-w-0 flex-1 items-center gap-1.5 rounded px-1 text-left text-label font-medium text-muted-foreground hover:text-text"
      >
        {folded[id] ? (
          <ChevronRight className="size-3 flex-shrink-0" />
        ) : (
          <ChevronDown className="size-3 flex-shrink-0" />
        )}
        <Icon className="size-3.5 flex-shrink-0 text-faint group-hover:text-muted-foreground" />
        <span className="truncate">{label}</span>
        <KeyBadge action={`rail.${id}`} />
      </button>
      {i === 0 && (
        <Tooltip content={railToggleTitle(true)} side="bottom">
          <button onClick={() => setOpen(false)} aria-label={railToggleTitle(true)} className={iconButtonClass("sm")}>
            <PanelRightClose />
          </button>
        </Tooltip>
      )}
    </div>
  );
  const section = (id: Tab) => <div className="min-h-0 flex-1 overflow-hidden">{body[id]}</div>;

  return (
    <aside ref={railRef} className="flex w-full min-w-0 flex-col overflow-hidden bg-surface/30">
      {!folded.agents && !folded.memory ? (
        <ResizablePanelGroup
          orientation="vertical"
          defaultLayout={defaultLayout}
          onLayoutChange={onLayoutChange}
          onLayoutChanged={onLayoutChanged}
        >
          {TABS.map(({ id, label, icon }, i) => (
            <Fragment key={id}>
              {i > 0 && <ResizableHandle />}
              <ResizablePanel id={id} minSize={SECTION_MIN} defaultSize="50" className="flex flex-col">
                {header(id, label, icon, i)}
                {section(id)}
              </ResizablePanel>
            </Fragment>
          ))}
        </ResizablePanelGroup>
      ) : (
        // A folded section is its header and nothing more; an open one takes
        // the rest of the rail. Both folded leave the rail's foot empty.
        TABS.map(({ id, label, icon }, i) =>
          folded[id] ? (
            <Fragment key={id}>{header(id, label, icon, i)}</Fragment>
          ) : (
            <div key={id} className="flex min-h-0 flex-1 flex-col">
              {header(id, label, icon, i)}
              {section(id)}
            </div>
          ),
        )
      )}
    </aside>
  );
}
