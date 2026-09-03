// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { MemoryPageView } from "@/components/memory-page-view";
import { GlobalStatusItems } from "@/components/status-items";
import { parseMemoryKeyParam } from "@/lib/memory-routes";

function MemoryPageBody() {
  const params = useParams();
  const roomName = params.name as string;
  const keySegments = params.key;
  const memoryKey = parseMemoryKeyParam(
    Array.isArray(keySegments) ? keySegments : keySegments ? [keySegments] : [],
  );

  return <MemoryPageView roomName={roomName} memoryKey={memoryKey} />;
}

/** Dedicated full-page memory route: `/room/{room}/memory/{key}`. */
export default function MemoryPage() {
  const params = useParams();
  const roomName = params.name as string;

  return (
    <AppShell
      activeRoom={roomName}
      statusLeft={<span className="text-micro text-muted-foreground">Memory</span>}
      statusRight={<GlobalStatusItems />}
    >
      <Suspense fallback={null}>
        <MemoryPageBody />
      </Suspense>
    </AppShell>
  );
}
