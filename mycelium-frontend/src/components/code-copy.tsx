// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";

/** True for 1.5s after `copy` writes to the clipboard. */
function useCopied() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  const copy = (text: string) => {
    if (!text) return;
    void navigator.clipboard?.writeText(text).then(() => setCopied(true));
  };
  return { copied, copy };
}

/** A fenced code block, with a Copy button in its corner on hover. */
export function CodeBlock({ children }: { children?: ReactNode }) {
  const pre = useRef<HTMLPreElement>(null);
  const { copied, copy } = useCopied();
  return (
    <div className="md-code">
      <pre ref={pre}>{children}</pre>
      <button
        type="button"
        onClick={() => copy((pre.current?.textContent ?? "").replace(/\n$/, ""))}
        className="md-code-copy"
        aria-label="Copy code"
      >
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** A code span that copies itself on a click. A drag still selects text,
 *  so a click that ends with a selection copies nothing. */
export function InlineCode({ children }: { children?: ReactNode }) {
  const code = useRef<HTMLElement>(null);
  const { copied, copy } = useCopied();
  return (
    // Below the span: a message's hover toolbar sits over its first line.
    <Tooltip
      side="bottom"
      openOnClick
      content={
        copied ? (
          <span className="inline-flex items-center gap-1 text-green" role="status">
            <Check className="size-3" />
            Copied
          </span>
        ) : (
          "Copy"
        )
      }
    >
      <code
        ref={code}
        className="md-code-inline"
        data-copied={copied || undefined}
        onClick={() => {
          if (window.getSelection()?.toString()) return;
          copy(code.current?.textContent ?? "");
        }}
      >
        {children}
      </code>
    </Tooltip>
  );
}
