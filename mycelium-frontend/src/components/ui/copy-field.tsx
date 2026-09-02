// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/** A read-only field with a copy button for text the user should copy rather
 * than retype. */
export function CopyField({ value, className }: { value: string; className?: string }) {
  const { copy, copied } = useCopy(value);

  return (
    <div className={cn("flex items-stretch gap-1.5", className)}>
      <input
        readOnly
        value={value}
        onFocus={(e) => e.currentTarget.select()}
        className="w-full min-w-0 rounded-lg bg-bg border border-border px-2 py-1.5 text-micro text-text outline-none focus:border-accent"
      />
      <CopyIconButton copied={copied} onClick={copy} />
    </div>
  );
}

/** A named action for a large handoff the user should copy but does not need to
 * read in a scrollable field. */
export function CopyAction({
  value,
  label,
  className,
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const { copy, copied } = useCopy(value);
  return (
    <Button type="button" variant="secondary" size="sm" onClick={copy} className={className}>
      {copied ? <Check className="size-3.5 text-green" /> : <Copy className="size-3.5" />}
      {copied ? "Copied" : label}
    </Button>
  );
}

function useCopy(value: string) {
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
  return { copy, copied };
}

function CopyIconButton({ copied, onClick }: { copied: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={copied ? "Copied" : "Copy"}
      className="flex-shrink-0 flex items-center justify-center rounded-lg border border-border px-2 text-muted-foreground hover:bg-surface hover:text-text transition-colors"
    >
      {copied ? (
        <Check className="size-3.5" style={{ color: "var(--green)" }} />
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
  );
}
