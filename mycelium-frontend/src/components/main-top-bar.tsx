// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV_TABS = [
  { id: "rooms", label: "Rooms", href: "/" },
  { id: "metrics", label: "Metrics", href: "/metrics" },
  { id: "memory", label: "Memory" },
  { id: "agents", label: "Agents" },
  { id: "logs", label: "Logs" },
];

interface MainTopBarProps {
  activeTab?: "rooms" | "metrics" | "memory" | "agents" | "logs";
  actions?: ReactNode;
}

export function MainTopBar({ activeTab = "rooms", actions }: MainTopBarProps) {
  return (
    <header className="flex h-[52px] flex-shrink-0 items-center gap-1 border-b border-border bg-surface/70 px-4 backdrop-blur">
      <Link href="/" className="flex items-center gap-2.5 rounded-md px-2 py-1 transition-colors hover:bg-hairline">
        <Image src="/logo.png" alt="Mycelium" width={22} height={22} className="opacity-90" />
        <span
          className="text-display leading-none text-text"
          style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
        >
          mycelium
        </span>
      </Link>

      <nav className="ml-4 flex items-center gap-0.5">
        {NAV_TABS.map(t => {
          const active = t.id === activeTab;
          if (t.href) {
            return (
              <Link
                key={t.id}
                href={t.href}
                className={`rounded-md px-3 py-1.5 text-label font-medium transition-colors ${
                  active
                    ? "bg-elevated text-text ring-1 ring-border"
                    : "text-muted-foreground hover:text-text hover:bg-hairline"
                }`}
              >
                {t.label}
              </Link>
            );
          }
          return (
            <span
              key={t.id}
              aria-disabled="true"
              title="coming soon"
              className="cursor-not-allowed rounded-md px-3 py-1.5 text-label font-medium text-faint select-none"
            >
              {t.label}
            </span>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-2">
        {actions}
        <ThemeToggle />
      </div>
    </header>
  );
}
