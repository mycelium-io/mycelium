// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// The onboarding tour is a plain imperative controller, not a hook: driver.js
// owns its own overlay/DOM/lifecycle, so wrapping it in React state adds
// ceremony without benefit. `startRoomTour` holds all the logic (steps,
// theming); a thin <RoomTour> seam wires it to `?tour=1`.

import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import type { View } from "@/lib/room-dock";
import type { Tab as InspectorTab } from "@/components/room-inspector";

export interface TourDeps {
  setEditorView: (v: View) => void;
  setInspectorTab: (t: InspectorTab) => void;
  /** Called when the tour finishes or is dismissed. */
  onExit: () => void;
}

export interface TourHandle {
  destroy: () => void;
}

interface TourStop {
  element: string;
  title: string;
  text: string;
  side: "top" | "right" | "bottom" | "left";
  align: "start" | "center" | "end";
  /** Show this view in the center before pointing at it. */
  view?: View;
  /** Open this rail section before pointing at it. */
  rail?: InspectorTab;
}

/** A walk around the room you are in: where things are and what they're for. */
export const TOUR_STOPS: TourStop[] = [
  {
    element: '[data-tour="rooms"]',
    title: "Your rooms",
    text: "A room is a team: the people and agents in it, the work they share, and what they've learned. Make one for each project.",
    side: "right",
    align: "start",
  },
  {
    element: '[data-tour="composer"]',
    title: "Talk to the room",
    text: "Write to everyone here. @ someone to ask them directly, and start with / for a command, like /task to put work on the board.",
    side: "top",
    align: "start",
  },
  {
    element: '[data-tour="tab-board"]',
    title: "The board",
    text: "The room's tasks, and who has each one. Every task has its own thread, so the talk about it stays with it instead of filling the channel.",
    side: "bottom",
    align: "start",
    view: "board",
  },
  {
    element: '[data-tour="inspector-agents"]',
    title: "Who's here",
    text: "The people and agents in this room. Add starts a coding agent on your machine and brings it in.",
    side: "left",
    align: "start",
    rail: "agents",
  },
  {
    element: '[data-tour="inspector-memory"]',
    title: "What the room knows",
    text: "Decisions, notes and context, kept as files every member can read and search. Fold a section by its header, or drag the line between them.",
    side: "left",
    align: "start",
    rail: "memory",
  },
  {
    element: '[data-tour="status-bar"]',
    title: "Status at a glance",
    text: "Your hub, the machines your agents run on, and this room. A dot appears when something needs a look.",
    side: "top",
    align: "start",
  },
];

export function startRoomTour(deps: TourDeps): TourHandle {
  const d: Driver = driver({
    showProgress: true,
    allowClose: true,
    overlayColor: "#05070a",
    overlayOpacity: 0.6,
    stagePadding: 6,
    stageRadius: 10,
    popoverClass: "mycelium-tour",
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Done",
    progressText: "{{current}} of {{total}}",
    onDestroyed: () => deps.onExit(),
    // A stop whose target isn't on the page (a folded rail, a narrow window)
    // is left out rather than shown pointing at nothing.
    steps: TOUR_STOPS.filter((s) => document.querySelector(s.element)).map((s) => ({
      element: s.element,
      popover: { title: s.title, description: s.text, side: s.side, align: s.align },
      onHighlightStarted: s.view
        ? () => deps.setEditorView(s.view as View)
        : s.rail
          ? () => deps.setInspectorTab(s.rail as InspectorTab)
          : undefined,
    })),
  });

  d.drive();

  return {
    destroy: () => {
      if (d.isActive()) d.destroy();
    },
  };
}

/** One step of a guide: the `data-guide` target it points at, and what it says. */
export interface GuideStop {
  at: string;
  title: string;
  text: string;
}

/**
 * A short guide through a page, one stop per `[data-guide="…"]` target, in the
 * room tour's look. A stop whose target is not on the page is left out, so a
 * guide written for every state of a page fits whichever state it opens on.
 */
export function startGuide(stops: GuideStop[], onExit: () => void): TourHandle | null {
  const present = stops.filter((s) => document.querySelector(`[data-guide="${s.at}"]`));
  if (present.length === 0) return null;
  const d: Driver = driver({
    showProgress: present.length > 1,
    allowClose: true,
    overlayColor: "#05070a",
    overlayOpacity: 0.55,
    stagePadding: 6,
    stageRadius: 8,
    popoverClass: "mycelium-tour",
    nextBtnText: "Next",
    prevBtnText: "Back",
    doneBtnText: "Done",
    progressText: "{{current}} of {{total}}",
    onDestroyed: onExit,
    steps: present.map((s) => ({
      element: `[data-guide="${s.at}"]`,
      popover: { title: s.title, description: s.text, side: "bottom", align: "start" },
    })),
  });
  d.drive();
  return {
    destroy: () => {
      if (d.isActive()) d.destroy();
    },
  };
}
