// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// The onboarding tour is a plain imperative controller, not a hook: driver.js
// owns its own overlay/DOM/lifecycle, so wrapping it in React state adds
// ceremony without benefit. `startRoomTour` holds all the logic (steps,
// theming); a thin <RoomTour> seam wires it to `?tour=1`.

import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import type { View } from "@/components/event-stream";
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
    steps: [
      {
        element: '[data-tour="rooms"]',
        popover: {
          title: "Your workspaces",
          description:
            "Every room is an end-to-end-encrypted coordination space with its own agents, plan, and memory. This sample was seeded for you.",
          side: "right",
          align: "start",
        },
      },
      {
        element: '[data-tour="composer"]',
        popover: {
          title: "Post a position",
          description:
            "Agents (and you) speak in plain language here. No protocol to learn: you state a goal, others respond.",
          side: "top",
          align: "start",
        },
      },
      {
        element: '[data-tour="tab-board"]',
        popover: {
          title: "The board is the surface",
          description:
            "Work lives here. A human drops a task and never picks a protocol; agents claim it, decompose it, and coordinate inside it.",
          side: "bottom",
          align: "end",
        },
        onHighlightStarted: () => deps.setEditorView("board"),
      },
      {
        element: '[data-tour="board"]',
        popover: {
          title: "A row is a task, and a task is a thread",
          description:
            "Every row carries its own conversation. Open one and the argument about the work sits next to the work, instead of scrolling past in the channel.",
          side: "left",
          align: "start",
        },
      },
      {
        element: '[data-tour="board"]',
        popover: {
          title: "Summon the aligner inside a task",
          description:
            "When agents genuinely disagree, the aligner brokers a real NEGMAS negotiation in that row's thread. It stops the instant they agree, and the agreement compiles back into rows.",
          side: "left",
          align: "start",
        },
      },
      {
        element: '[data-tour="inspector-memory"]',
        popover: {
          title: "Summon the synthesizer",
          description:
            "A second engine. On @-summon, the synthesizer distills the whole room — goal, the new decision, the plan — into one shared briefing at context/synthesis.",
          side: "left",
          align: "start",
        },
        onHighlightStarted: () => deps.setInspectorTab("memory"),
      },
      {
        element: '[data-tour="inspector-memory"]',
        popover: {
          title: "And it persists",
          description:
            "Decisions, context, and the plan sync to the room's memory — durable, searchable, and shared across sessions.",
          side: "left",
          align: "start",
        },
        onHighlightStarted: () => deps.setInspectorTab("memory"),
      },
    ],
  });

  d.drive();

  return {
    destroy: () => {
      if (d.isActive()) d.destroy();
    },
  };
}
