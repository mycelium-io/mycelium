// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

/** A read-only, monospace input with a copy button — for a command or value the
 *  user should copy rather than retype. Selects on focus; shows a check on copy. */
export function CopyField({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (insecure context) — the field is still selectable
    }
  };

  return (
    <div className={cn("flex items-stretch gap-1.5", className)}>
      <input
        readOnly
        value={value}
        onFocus={(e) => e.currentTarget.select()}
        className="w-full min-w-0 bg-bg border border-border px-2 py-1.5 font-mono text-micro text-text outline-none focus:border-accent"
      />
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy"}
        className="flex-shrink-0 flex items-center justify-center border border-border px-2 text-muted-foreground hover:bg-surface hover:text-text transition-colors"
      >
        {copied ? (
          <Check className="size-3.5" style={{ color: "var(--green)" }} />
        ) : (
          <Copy className="size-3.5" />
        )}
      </button>
    </div>
  );
}
