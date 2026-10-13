// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The verifier's line under a message: what it couldn't confirm, in its own
 * words, with *Show why* (the records it read) and *It's fine* (dismiss it for
 * everyone, which the verifier learns from). A line whose records say the
 * opposite of the claim is drawn in the text color, so it reads surer than one
 * that only found nothing.
 */

import { useState } from "react";
import { CircleAlert } from "lucide-react";
import { markVerifierFlagFine, type VerifierFlag } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { FAILURE_NAMES } from "@/lib/verifier";

const ACTION =
  "underline decoration-border2 underline-offset-2 transition-colors hover:text-text hover:decoration-current disabled:opacity-50";

export function VerifierLines({
  roomName,
  flags,
  onChanged,
}: {
  roomName: string;
  flags: VerifierFlag[];
  /** Re-read the flags once one is answered. */
  onChanged?: () => void;
}) {
  return (
    <>
      {flags.map((flag) => (
        <VerifierLine key={flag.flag_id} roomName={roomName} flag={flag} onChanged={onChanged} />
      ))}
    </>
  );
}

function VerifierLine({
  roomName,
  flag,
  onChanged,
}: {
  roomName: string;
  flag: VerifierFlag;
  onChanged?: () => void;
}) {
  const { principal } = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  const fine = async () => {
    setBusy(true);
    setError(null);
    try {
      await markVerifierFlagFine(roomName, flag.flag_id, principal.trim() || undefined);
      // Gone at once here; the `check` notice takes it away for everyone else.
      setHidden(true);
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-verifier-flag={flag.flag_id}
      className="mt-1.5 grid grid-cols-[14px_1fr] gap-x-2 text-micro leading-[18px] text-muted-foreground"
    >
      <CircleAlert aria-hidden className="mt-[2px] size-3.5 text-yellow" />
      <span className="min-w-0">
        <span className="font-medium text-yellow">{flag.by || "verifier"}</span>
        <span className="text-faint"> · </span>
        <span className={cn(flag.sure && "font-medium text-text")}>{flag.line}</span>
        <span className="ml-3 whitespace-nowrap">
          <Popover>
            <PopoverTrigger className={ACTION}>Show why</PopoverTrigger>
            <PopoverContent align="start" className="w-80 p-3">
              <ShowWhy flag={flag} />
            </PopoverContent>
          </Popover>
          <span className="text-faint"> · </span>
          <Tooltip content="Marks this claim as fine. The verifier learns from it.">
            <button type="button" className={ACTION} disabled={busy} onClick={() => void fine()}>
              It&apos;s fine
            </button>
          </Tooltip>
        </span>
        {error && <span className="ml-2 text-red">{error}</span>}
      </span>
    </div>
  );
}

/** What the verifier read to reach its line. */
function ShowWhy({ flag }: { flag: VerifierFlag }) {
  const checked = flag.checked ?? [];
  const failure = flag.failure ? FAILURE_NAMES[flag.failure] : undefined;
  return (
    <div className="space-y-2 text-micro">
      {failure && <p className="font-medium text-text">{failure}</p>}
      <p className="text-muted-foreground">
        @{flag.about} said <span className="text-text">&ldquo;{flag.sentence}&rdquo;</span>
      </p>
      {flag.why && <p className="text-text">{flag.why}</p>}
      {checked.length > 0 && (
        <ul className="space-y-1">
          {checked.map((c, i) => (
            <li key={`${c.what}-${i}`} className="flex gap-2">
              <span className="min-w-0 flex-1 text-muted-foreground">{c.what}</span>
              <span className="flex-shrink-0 text-text">{c.found}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-faint">It only reads this room&apos;s records.</p>
    </div>
  );
}
