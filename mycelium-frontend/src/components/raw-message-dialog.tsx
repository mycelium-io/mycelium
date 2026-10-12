// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CopyAction } from "@/components/ui/copy-field";
import { highlightJson } from "@/lib/json-highlight";

/** One message exactly as the hub sent it: every field, including the
 *  envelope agents and engines exchange, which the chat doesn't show. */
export function RawMessageDialog({
  open,
  onClose,
  message,
}: {
  open: boolean;
  onClose: () => void;
  message: Record<string, unknown> | null;
}) {
  const text = message ? JSON.stringify(message, null, 2) : "";
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Raw message</DialogTitle>
        </DialogHeader>
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-bg p-3 font-mono text-micro leading-relaxed text-text">
          {highlightJson(text)}
        </pre>
        <div className="flex justify-end">
          <CopyAction value={text} label="Copy JSON" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
