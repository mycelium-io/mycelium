// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef } from "react";
import { startRoomTour, type TourDeps, type TourHandle } from "@/lib/tour";

/** What has to be on the page before the tour starts, and how long to wait for it. */
const ROOM_READY = '[data-tour="composer"]';
const READY_WAIT_MS = 4000;

interface Props extends TourDeps {
  /** Start the tour when this flips true (e.g. `?tour=1`). */
  active: boolean;
}

/** Thin seam: starts the imperative tour controller. */
export function RoomTour({ active, setEditorView, setInspectorTab, onExit }: Props) {
  const handleRef = useRef<TourHandle | null>(null);

  useEffect(() => {
    if (!active) return;
    // The tour leaves out stops it can't see, and the room's center (the
    // composer, the Board tab) mounts after the page does, so it waits for
    // that, briefly, rather than starting on half a room.
    const started = Date.now();
    const timer = setInterval(() => {
      if (!document.querySelector(ROOM_READY) && Date.now() - started < READY_WAIT_MS) return;
      clearInterval(timer);
      handleRef.current = startRoomTour({ setEditorView, setInspectorTab, onExit });
    }, 100);
    return () => {
      clearInterval(timer);
      handleRef.current?.destroy();
      handleRef.current = null;
    };
    // Start once per activation; deps are read fresh via the closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return null;
}
