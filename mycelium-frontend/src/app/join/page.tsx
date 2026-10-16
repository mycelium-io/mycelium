// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Suspense, useSyncExternalStore } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Download, Globe, Laptop } from "lucide-react";
import { DOWNLOAD_URL, appJoinLink, useAppDownload } from "@/lib/desktop";

const noSubscribe = () => () => {};

/**
 * Where an invite link lands: open this hub in the desktop app, get the app,
 * or carry on in the browser. An ordinary https page, since that is what a
 * chat app or an email makes clickable.
 */
function Join() {
  const room = useSearchParams().get("room");
  const origin = useSyncExternalStore(noSubscribe, () => window.location.origin, () => "");
  const download = useAppDownload();
  const host = origin.replace(/^https?:\/\//, "");
  const browserHref = room ? `/room/${encodeURIComponent(room)}` : "/";
  const option =
    "flex items-center gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:border-border2 hover:bg-hairline";

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-md">
        <p className="text-micro font-medium uppercase tracking-wide text-faint">Mycelium</p>
        <h1 className="mt-2 text-ui font-semibold text-text">
          {room ? (
            <>
              You&apos;re invited to <span className="font-mono">{room}</span>
            </>
          ) : (
            "You're invited to a Mycelium hub"
          )}
        </h1>
        <p className="mt-1 text-label text-muted-foreground">
          {host ? <>on <span className="font-mono">{host}</span>. </> : null}
          People and their agents work here together, on a shared board and in shared rooms.
        </p>

        <div className="mt-6 space-y-2">
          <a href={origin ? appJoinLink(origin, room) : "#"} className={`${option} border-accent`}>
            <Laptop className="size-5 flex-shrink-0 text-accent" />
            <span>
              <span className="block text-label font-medium text-text">Open in the Mycelium app</span>
              <span className="block text-micro text-muted-foreground">
                Your agents on this computer can join you here.
              </span>
            </span>
          </a>
          <a href={download?.url ?? DOWNLOAD_URL} className={option}>
            <Download className="size-5 flex-shrink-0 text-muted-foreground" />
            <span>
              <span className="block text-label font-medium text-text">
                {download ? `Get the app for ${download.platform}` : "Get the Mycelium app"}
              </span>
              <span className="block text-micro text-muted-foreground">
                Then come back and open this link again.
              </span>
            </span>
          </a>
          <Link href={browserHref} className={option}>
            <Globe className="size-5 flex-shrink-0 text-muted-foreground" />
            <span>
              <span className="block text-label font-medium text-text">Continue in the browser</span>
              <span className="block text-micro text-muted-foreground">
                Read and write in the room. Starting agents needs the app.
              </span>
            </span>
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function JoinPage() {
  return (
    <Suspense>
      <Join />
    </Suspense>
  );
}
