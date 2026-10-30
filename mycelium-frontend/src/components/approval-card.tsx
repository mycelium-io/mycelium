// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Check, CircleHelp, ExternalLink, FileText, X } from "lucide-react";
import { answerAsk } from "@/lib/api";
import { linkKind, type ApprovalAsk, type AskAnswer } from "@/lib/approvals";
import { useCurrentUser } from "@/components/current-user";
import { nameOf, useNames } from "@/lib/people";
import { useRoomRevalidate } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";

/**
 * An agent's ask for one person's OK, drawn where the agent asked it: what it
 * wants to do, then whichever of what happens, why now and how to undo it the
 * agent gave. Only the person asked gets Approve and Decline; everyone else sees
 * whom it waits on. Once answered it stays as the record of who decided, when,
 * and why not.
 */
/** The ask's link: a page opens in a new tab, a memory opens in the room, and
 *  anything else is shown as written. */
function AskLink({ link, onOpenMemory }: { link: string; onOpenMemory?: (key: string) => void }) {
  const kind = linkKind(link);
  const look = "mt-2 inline-flex max-w-full items-center gap-1 text-label";
  if (kind === "web") {
    return (
      <a href={link} target="_blank" rel="noreferrer" className={cn(look, "text-accent hover:underline")}>
        <ExternalLink className="size-3.5 flex-shrink-0" />
        <span className="truncate">{link}</span>
      </a>
    );
  }
  if (kind === "memory" && onOpenMemory) {
    return (
      <button type="button" onClick={() => onOpenMemory(link)} className={cn(look, "font-mono text-accent hover:underline")}>
        <FileText className="size-3.5 flex-shrink-0" />
        <span className="truncate">{link}</span>
      </button>
    );
  }
  return <p className={cn(look, "break-all text-muted-foreground")}>{link}</p>;
}

export function ApprovalCard({
  roomName,
  ask,
  onOpenMemory,
}: {
  roomName: string;
  ask: ApprovalAsk;
  /** Opens a memory the ask links to, as a link in a message does. */
  onOpenMemory?: (key: string) => void;
}) {
  const { principal } = useCurrentUser();
  const names = useNames();
  const revalidate = useRoomRevalidate(roomName);
  // The answer shows at once; the hub's copy, folded onto the ask, replaces it
  // on the next read.
  const [sent, setSent] = useState<AskAnswer | null>(null);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const answer = ask.answer ?? sent;
  const me = principal.trim().replace(/^@/, "").toLowerCase();
  const mine = me !== "" && me === ask.to.replace(/^@/, "").toLowerCase();
  const waitsOnMe = mine && !answer;
  const who = (handle: string) => nameOf(names, handle) ?? handle;

  const send = async (decision: AskAnswer["decision"]) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const why = decision === "declined" ? reason.trim() || null : null;
    try {
      await answerAsk(roomName, ask.id, { decision, reason: why, by: me });
      setSent({ decision, reason: why, by: me, at: new Date().toISOString() });
      setDeclining(false);
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send that.");
    } finally {
      setBusy(false);
    }
  };

  const facts: [string, string][] = [];
  if (ask.happens) facts.push(["What happens", ask.happens]);
  if (ask.why) facts.push(["Why now", ask.why]);
  if (ask.undo) facts.push(["To undo", ask.undo]);

  return (
    <div
      data-ask={ask.id}
      className={cn("mt-1.5 max-w-2xl rounded-lg border bg-surface", waitsOnMe ? "border-yellow/40" : "border-border")}
    >
      <div className="px-3 pt-2.5 pb-2.5">
        {/* It needs an OK only from the person asked, and only until they give one. */}
        <div className="flex items-center gap-1.5 text-micro">
          <CircleHelp className={cn("size-3.5", waitsOnMe ? "text-yellow" : "text-faint")} />
          <span className={waitsOnMe ? "font-medium text-yellow" : "text-muted-foreground"}>
            {waitsOnMe ? "Needs your OK" : "Approval"}
          </span>
          <span className="text-faint">·</span>
          <span className="text-muted-foreground">asks {who(ask.to)}</span>
        </div>
        <p className="mt-1 text-body font-medium text-text">{ask.question}</p>
        {facts.length > 0 && (
          <dl className="mt-2 grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-label">
            {facts.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-text">{value}</dd>
              </div>
            ))}
          </dl>
        )}
        {ask.link && <AskLink link={ask.link} onOpenMemory={onOpenMemory} />}
      </div>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 border-t border-border px-3 py-1.5">
        {answer ? (
          <div className="min-w-0 text-label">
            <span className="flex items-center gap-1.5 text-text">
              {answer.decision === "approved" ? (
                <Check className="size-3.5 flex-shrink-0 text-green" />
              ) : (
                <X className="size-3.5 flex-shrink-0 text-red" />
              )}
              {answer.decision === "approved" ? "Approved" : "Declined"} by {who(answer.by)}
              {answer.at && <Ago at={answer.at} className="text-micro text-faint" />}
            </span>
            {answer.reason && <p className="mt-0.5 pl-5 text-muted-foreground">“{answer.reason}”</p>}
          </div>
        ) : !mine ? (
          <span className="text-label text-muted-foreground">Waiting on {who(ask.to)}</span>
        ) : declining ? (
          <form
            className="flex min-w-0 flex-1 items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void send("declined");
            }}
          >
            <input
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setDeclining(false);
              }}
              placeholder="Why not (optional)"
              aria-label="Why not"
              className="h-6 min-w-0 flex-1 rounded-md border border-border2 bg-bg px-2 text-label text-text outline-none placeholder:text-faint focus:border-accent"
            />
            <Button type="submit" size="xs" variant="outline" disabled={busy}>
              Decline <Kbd size="xs" tone="muted">↵</Kbd>
            </Button>
            <Button type="button" size="xs" variant="ghost" onClick={() => setDeclining(false)}>
              Cancel
            </Button>
          </form>
        ) : (
          <>
            <Button size="xs" disabled={busy} onClick={() => void send("approved")}>
              <Check className="size-3.5" /> Approve
            </Button>
            <Button size="xs" variant="ghost" disabled={busy} onClick={() => setDeclining(true)}>
              Decline…
            </Button>
          </>
        )}
        {error && (
          <span role="alert" className="text-micro text-red">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
