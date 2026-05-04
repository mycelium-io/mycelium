// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import Link from "next/link";
import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";

const crumbs: Crumb[] = [{ label: "metrics" }];

export default function MetricsLanding() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar activeTab="metrics" />
      <SubNav crumbs={crumbs} />

      <main className="flex flex-1 items-center justify-center gap-8 p-8">
        <StyleCard
          href="/metrics/cards"
          title="Cards"
          description="Grouped metric cards with accent borders. Good for scanning at a glance."
          preview={["┌─ EMBEDDINGS ─────┐", "│ computed     38  │", "│ est tokens 3.2k  │", "└─────────────────-┘"]}
        />
        <StyleCard
          href="/metrics/tables"
          title="Tables"
          description="Dense monospace tables with aligned columns. Closer to the CLI output."
          preview={["EMBEDDINGS", "─────────────────────", "computed      │    38", "est tokens    │ 3,226"]}
        />
      </main>
    </div>
  );
}

function StyleCard({
  href,
  title,
  description,
  preview,
}: {
  href: string;
  title: string;
  description: string;
  preview: string[];
}) {
  return (
    <Link
      href={href}
      className="group flex w-[340px] flex-col border border-border bg-paper transition-colors hover:border-accent/40 hover:bg-surface"
    >
      <div className="border-b border-border bg-surface/40 px-5 py-3">
        <span className="caps-mono text-text group-hover:text-accent transition-colors">{title}</span>
      </div>
      <div className="px-5 py-4">
        <pre className="text-micro text-dim leading-relaxed mb-4 font-mono" style={{ fontFamily: "var(--font-mono)" }}>
          {preview.join("\n")}
        </pre>
        <p className="text-micro text-muted leading-relaxed">{description}</p>
      </div>
    </Link>
  );
}
