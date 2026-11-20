// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { noteHerdr, type HerdrState } from "@/lib/activity";
import { useRoomMembers } from "@/lib/room-data";

/** What herdr says each agent on a machine in the room is doing, from the same
 *  members read the agent panel shows, with when each one last changed. */
export function useHerdrState(room: string): ReadonlyMap<string, HerdrState> {
  const { members } = useRoomMembers(room);
  const [herdr, setHerdr] = useState<ReadonlyMap<string, HerdrState>>(() => new Map());
  useEffect(() => {
    // The time a status changed is when this view read it, so it is taken
    // as each read arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHerdr((prev) => noteHerdr(prev, members, Date.now()));
  }, [members]);
  return herdr;
}
