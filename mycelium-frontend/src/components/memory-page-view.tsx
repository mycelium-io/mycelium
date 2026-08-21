// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";
import {
  fetchMemory,
  fetchMemoryExpanded,
  type Memory,
} from "@/lib/api";
import { useRoomMemoryIntegrity } from "@/lib/room-data";
import { memoryHref } from "@/lib/memory-routes";
import { MemoryDetail } from "@/components/memory-detail";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  roomName: string;
  memoryKey: string;
}

/** Full-page wiki view for one memory. */
export function MemoryPageView({ roomName, memoryKey }: Props) {
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null | undefined>(undefined);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  const { integrity } = useRoomMemoryIntegrity(roomName);

  useEffect(() => {
    let live = true;
    setMemory(undefined);
    setRenderedBody(null);
    fetchMemory(roomName, memoryKey).then(m => {
      if (!live) return;
      setMemory(m);
    });
    fetchMemoryExpanded(roomName, memoryKey).then(exp => {
      if (!live || !exp.found || !exp.rendered) return;
      setRenderedBody(exp.rendered);
    });
    return () => {
      live = false;
    };
  }, [roomName, memoryKey]);

  const onNavigate = useCallback(
    (key: string) => router.push(memoryHref(roomName, key)),
    [router, roomName],
  );

  if (memory === undefined) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    );
  }

  if (memory === null) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-10">
        <p className="text-body text-muted-foreground">Memory not found.</p>
        <Link
          href={`/room/${encodeURIComponent(roomName)}`}
          className="mt-4 inline-flex items-center gap-1 text-label text-accent"
        >
          <ChevronLeft className="size-4" />
          Back to room
        </Link>
      </div>
    );
  }

  const crumbs = memoryKey.split("/");

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/90 px-6 py-3 backdrop-blur-sm md:px-8">
        <Link
          href={`/room/${encodeURIComponent(roomName)}`}
          className="mb-2 inline-flex items-center gap-1 text-micro text-muted-foreground transition-colors hover:text-accent"
        >
          <ChevronLeft className="size-3.5" />
          {roomName}
        </Link>
        <h1 className="font-mono text-ui font-semibold text-text break-all">
          {crumbs.map((part, i) => (
            <span key={i}>
              {i > 0 && <span className="text-faint">/</span>}
              {part}
            </span>
          ))}
        </h1>
      </header>

      <div className="mx-auto w-full max-w-3xl pb-12">
        <MemoryDetail
          memory={memory}
          roomName={roomName}
          onNavigate={onNavigate}
          variant="page"
          renderedBody={renderedBody}
          integrity={integrity}
        />
      </div>
    </div>
  );
}
