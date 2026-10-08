// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Suspense, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { MemoryView } from "@/components/memory-view";
import { memoryHref, parseMemoryKeyParam, parseRoomNameParam } from "@/lib/memory-routes";

function MemoryPageBody() {
  const params = useParams();
  const router = useRouter();
  const roomName = parseRoomNameParam(params.name as string);
  const keySegments = params.key;
  const memoryKey = parseMemoryKeyParam(
    Array.isArray(keySegments) ? keySegments : keySegments ? [keySegments] : [],
  );
  const openMemory = useCallback(
    (key: string) => router.push(memoryHref(roomName, key)),
    [router, roomName],
  );

  // Keyed on the memory, so following a link starts the view over rather than
  // showing the last memory under the next one's address.
  return (
    <MemoryView
      key={memoryKey}
      roomName={roomName}
      memoryKey={memoryKey}
      onOpenMemory={openMemory}
      layout="page"
    />
  );
}

/** A memory, full page: the same view a room opens as a tab, at
 *  `/room/{room}/memory/{key}`. */
export default function MemoryPage() {
  const params = useParams();
  const roomName = parseRoomNameParam(params.name as string);

  return (
    <AppShell
      activeRoom={roomName}
    >
      <Suspense fallback={null}>
        <MemoryPageBody />
      </Suspense>
    </AppShell>
  );
}
