// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { AccountMenu } from "@/components/account-menu";
import { KeyBadge } from "@/components/key-badge";
import { NotificationBell } from "@/components/notification-bell";
import { desktopMachine, useIsDesktop } from "@/lib/desktop";

const noSubscribe = () => () => {};

/**
 * Which hub this is, as the title bar names it: a hub on this computer by
 * that ("This Mac" in the app on a Mac), any other by its host name. Never a port,
 * which says nothing to a person. Empty while rendering on the server.
 */
export function hubLabel(host: string, desktop: boolean, machine: string = desktopMachine()): string {
  const name = host.replace(/:\d+$/, "");
  if (/^(127\.0\.0\.1|localhost|\[::1\])$/.test(name)) return desktop ? `This ${machine}` : "This computer";
  return name;
}

export function useHubLabel(): string {
  const desktop = useIsDesktop();
  const host = useSyncExternalStore(noSubscribe, () => window.location.host, () => "");
  return hubLabel(host, desktop);
}

/**
 * The strip across the top of every screen, the way an editor draws one:
 * where you are on the left (the hub, then the page), and who you are on the
 * right. Thin, and the same in a browser and in the Mac app.
 */
export function TitleBar({ crumb, right }: { crumb?: ReactNode; right?: ReactNode }) {
  const hub = useHubLabel();
  return (
    <header className="flex h-9 flex-shrink-0 items-center gap-1 border-b border-border bg-surface px-2 text-label">
      <Link
        href="/"
        className="relative flex min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
      >
        <Image src="/logo.png" alt="Mycelium" width={16} height={16} className="flex-shrink-0 opacity-90" />
        <span className="truncate font-medium">{hub || "Mycelium"}</span>
        <KeyBadge action="nav.home" />
      </Link>
      {crumb && (
        <>
          <span aria-hidden className="text-faint">
            /
          </span>
          <div className="flex min-w-0 items-center gap-1 text-text">{crumb}</div>
        </>
      )}
      <div className="ml-auto flex flex-shrink-0 items-center gap-0.5">
        {right}
        <NotificationBell />
        <AccountMenu />
      </div>
    </header>
  );
}
