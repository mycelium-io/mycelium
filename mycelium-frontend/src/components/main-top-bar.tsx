// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

const NAV_TABS = [
  { id: "rooms", label: "ROOMS", href: "/" },
  { id: "logs", label: "LOGS", href: "/logs" },
  { id: "memory", label: "MEMORY" },
  { id: "agents", label: "AGENTS" },
];

interface MainTopBarProps {
  activeTab?: "rooms" | "logs" | "memory" | "agents";
  actions?: ReactNode;
}

export function MainTopBar({ activeTab = "rooms", actions }: MainTopBarProps) {
  return (
    <header className="flex h-[52px] flex-shrink-0 items-stretch border-b border-border2 bg-surface/80 backdrop-blur">
      <Link href="/" className="flex items-center gap-3 border-r border-border px-5 transition-colors hover:bg-white/[0.025]">
        <Image src="/logo.png" alt="Mycelium" width={22} height={22} className="opacity-90" />
        <span
          className="text-display leading-none text-text"
          style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
        >
          mycelium
        </span>
      </Link>

      <nav className="flex items-stretch border-r border-border px-3">
        {NAV_TABS.map(t => {
          const active = t.id === activeTab;
          if (t.href) {
            return (
              <Link
                key={t.id}
                href={t.href}
                className={`flex items-center px-3 caps-mono-sm transition-colors ${
                  active ? "text-accent" : "text-text2 hover:text-text"
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
              className="flex items-center px-3 caps-mono-sm text-dim cursor-not-allowed select-none"
            >
              {t.label}
            </span>
          );
        })}
      </nav>

      <div className="flex flex-1 items-center justify-end gap-3 px-5">
        {actions}
      </div>
    </header>
  );
}
