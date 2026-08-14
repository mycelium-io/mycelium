// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Activity, Brain, PanelRightClose, PanelRightOpen, Users, type LucideIcon } from "lucide-react";
import { AgentsPanel } from "@/components/agents-panel";
import { EpisodesRail } from "@/components/episodes-rail";
import { MemoryPanel } from "@/components/memory-panel";

export type Tab = "agents" | "episodes" | "memory";

const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: "agents", label: "Members", icon: Users },
  { id: "episodes", label: "Episodes", icon: Activity },
  { id: "memory", label: "Memory", icon: Brain },
];

interface Props {
  roomName: string;
  masId?: string | null;
  memoryRefresh: number;
  /** Optional controlled tab + open state (e.g. driven from the status bar). */
  tab?: Tab;
  onTabChange?: (tab: Tab) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/** The room's context, consolidated: agents, episodes, and memory behind one
 *  tabbed right rail (Model B) instead of sprawling across both sides. */
export function RoomInspector({
  roomName,
  masId,
  memoryRefresh,
  tab: tabProp,
  onTabChange,
  open: openProp,
  onOpenChange,
}: Props) {
  const [tabInternal, setTabInternal] = useState<Tab>("agents");
  const [openInternal, setOpenInternal] = useState(true);
  const tab = tabProp ?? tabInternal;
  const open = openProp ?? openInternal;
  const setTab = (t: Tab) => { if (tabProp === undefined) setTabInternal(t); onTabChange?.(t); };
  const setOpen = (o: boolean) => { if (openProp === undefined) setOpenInternal(o); onOpenChange?.(o); };

  // Collapsed: a slim strip of the three tab icons; clicking one expands to it.
  if (!open) {
    return (
      <aside className="flex w-12 flex-shrink-0 flex-col items-center gap-1 border-l border-border bg-surface/40 pt-3">
        <button
          onClick={() => setOpen(true)}
          aria-label="Open inspector"
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
            className={`flex size-9 items-center justify-center rounded-lg transition-colors hover:bg-surface hover:text-text ${
              tab === id ? "text-accent" : "text-muted-foreground"
            }`}
          >
            <Icon className="size-[18px]" />
          </button>
        ))}
      </aside>
    );
  }

  return (
    <aside className="flex w-[340px] flex-shrink-0 flex-col border-l border-border bg-surface/30">
      <div className="flex h-[48px] flex-shrink-0 items-center gap-1 border-b border-border bg-paper px-2">
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                data-tour={`inspector-${id}`}
                onClick={() => setTab(id)}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-label font-medium transition-colors ${
                  active ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-text"
                }`}
              >
                <Icon className="size-3.5" />
                {label}
              </button>
            );
          })}
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Collapse inspector"
          className="ml-auto flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <PanelRightClose className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "agents" && <AgentsPanel roomName={roomName} refreshKey={memoryRefresh} />}
        {tab === "episodes" && <EpisodesRail roomName={roomName} />}
        {tab === "memory" && (
          <MemoryPanel roomName={roomName} masId={masId ?? null} refreshTrigger={memoryRefresh} />
        )}
      </div>
    </aside>
  );
}
