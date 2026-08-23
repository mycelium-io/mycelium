// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// The onboarding tour is a plain imperative controller, not a hook: driver.js
// owns its own overlay/DOM/lifecycle, so wrapping it in React state adds
// ceremony without benefit. `startRoomTour` holds all the logic (steps,
// theming, convergence sync); a thin <RoomTour> seam wires it to `?tour=1`.

import { driver, type Driver } from "driver.js";
import "driver.js/dist/driver.css";
import type { View } from "@/components/event-stream";
import type { Tab as InspectorTab } from "@/components/room-inspector";

export type NegotiationPhase = "idle" | "negotiating" | "converged" | "rejected";

export interface TourDeps {
  setEditorView: (v: View) => void;
  setInspectorTab: (t: InspectorTab) => void;
  /** Called when the tour finishes or is dismissed. */
  onExit: () => void;
}

export interface TourHandle {
  destroy: () => void;
  /** Feed the live negotiation phase so the tour can pace itself to it. */
  notifyPhase: (phase: NegotiationPhase) => void;
}

// Step indices that live inside the Negotiate view — when the sample
// negotiation converges while the user is parked on the offer board or swim
// lanes, we jump them straight to the consensus reveal (the synced payoff).
const OFFER_BOARD_STEP = 3;
const SWIMLANES_STEP = 4;
const CONSENSUS_STEP = 5;

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
        element: '[data-tour="tab-negotiate"]',
        popover: {
          title: "Summon the aligner",
          description:
            "When a room needs to decide something, the aligner brokers a real NEGMAS negotiation. Open it and watch this sample resolve.",
          side: "bottom",
          align: "end",
        },
        onHighlightStarted: () => deps.setEditorView("negotiate"),
      },
      {
        element: '[data-tour="offer-board"]',
        popover: {
          title: "Offers, interpreted live",
          description:
            "Each natural-language reply is snapped to a move on the negotiation grid. The standing offer updates every round.",
          side: "left",
          align: "start",
        },
      },
      {
        element: '[data-tour="swimlanes"]',
        popover: {
          title: "Round by round",
          description:
            "Agents propose, counter, and accept. The aligner addresses one at a time until they converge — or it stops without agreement.",
          side: "left",
          align: "start",
        },
      },
      {
        element: '[data-tour="consensus"]',
        popover: {
          title: "Unanimity, not theatre",
          description:
            "The mechanism stops the instant they agree. GAR scores how genuinely each agent moved toward the outcome.",
          side: "bottom",
          align: "end",
        },
      },
      {
        element: '[data-tour="tab-plan"]',
        popover: {
          title: "Consensus becomes a plan",
          description:
            "The agreement compiles into a shared checklist with per-agent owners, before it is even announced.",
          side: "bottom",
          align: "end",
        },
        onHighlightStarted: () => deps.setEditorView("board"),
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
    notifyPhase: (phase) => {
      if (!d.isActive()) return;
      const i = d.getActiveIndex();
      if (phase === "converged" && (i === OFFER_BOARD_STEP || i === SWIMLANES_STEP)) {
        d.moveTo(CONSENSUS_STEP);
      }
    },
  };
}
