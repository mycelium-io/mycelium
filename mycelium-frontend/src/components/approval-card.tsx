// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  FileText,
  ListChecks,
  MessageCircleQuestion,
  X,
} from "lucide-react";
import { answerAsk } from "@/lib/api";
import { linkKind, verdictOf, type ApprovalAsk, type AskAnswer, type AskKind, type Decision } from "@/lib/approvals";
import { useCurrentUser } from "@/components/current-user";
import { nameOf, useNames } from "@/lib/people";
import { useRoomRevalidate } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<AskKind, typeof CircleHelp> = {
  approve: CircleHelp,
  choose: ListChecks,
  question: MessageCircleQuestion,
};

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

/** What it asks, in the card's first line: to the person asked, what they're to
 *  do; to anyone else, whom it asks. */
function heading(ask: ApprovalAsk, mine: boolean, to: string): string {
  if (!mine) return `Asks ${to}`;
  if (ask.kind === "approve") return "Needs your OK";
  if (ask.kind === "choose") return ask.multiple ? "Pick any" : "Pick one";
  return "Asks you";
}

/**
 * An agent's ask, drawn where the agent asked it: in the room's channel or a
 * task's thread. It's put to one person, who sees it as theirs; anyone else in
 * the room sees whom it asks and may answer it too. Every kind takes a note
 * with its answer. Once answered it folds to the question, with what was
 * answered under it and who answered when beside it, and opens to the whole
 * record.
 *
 * Everything in it is text that wraps, or is cut with an ellipsis inside the
 * card: no columns, and nothing that refuses to shrink. A fact is a paragraph
 * with its label run in, and an option is one sentence (its number, its text
 * and whether it's recommended), so a long one wraps as a whole.
 */
export function AskCard({
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
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(ask.suggest ?? "");
  const [picked, setPicked] = useState<string[]>(ask.recommend);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const answer = ask.answer ?? sent;
  const me = principal.trim().replace(/^@/, "").toLowerCase();
  const mine = me !== "" && me === ask.to.replace(/^@/, "").toLowerCase();
  const who = (handle: string) => (handle.toLowerCase() === me ? "you" : (nameOf(names, handle) ?? handle));
  const Icon = KIND_ICON[ask.kind];

  const send = async (decision?: Decision) => {
    if (busy || !me) return;
    const text = note.trim() || null;
    if (ask.kind === "question" && !text) return;
    if (ask.kind === "choose" && (picked.length === 0 || (!ask.multiple && picked.length > 1))) return;
    setBusy(true);
    setError(null);
    const choices = ask.kind === "choose" ? ask.options.filter((o) => picked.includes(o.id)).map((o) => o.id) : [];
    try {
      await answerAsk(roomName, ask.id, {
        by: me,
        ...(decision ? { decision } : {}),
        ...(ask.kind === "choose" ? { choices } : {}),
        ...(text ? { text } : {}),
      });
      setSent({
        kind: ask.kind,
        question: ask.question,
        for: ask.to,
        by: me,
        at: new Date().toISOString(),
        decision: decision ?? null,
        choices,
        chosen: ask.options.filter((o) => choices.includes(o.id)).map((o) => o.label),
        text,
      });
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send that.");
    } finally {
      setBusy(false);
    }
  };

  // Answered: the question, and under it what was answered, each cut to fit
  // the card. It opens to the whole record.
  if (answer && !open) {
    const declined = answer.kind === "approve" && answer.decision === "declined";
    return (
      <button
        type="button"
        data-ask={ask.id}
        onClick={() => setOpen(true)}
        aria-expanded={false}
        className="mt-1.5 grid w-full max-w-2xl grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-left text-label hover:bg-hairline"
      >
        {declined ? (
          <X className="size-3.5 self-center text-red" aria-hidden />
        ) : (
          <Check className="size-3.5 self-center text-green" aria-hidden />
        )}
        <span className="truncate text-text">{ask.question}</span>
        <span className="flex items-center gap-1 text-micro whitespace-nowrap text-faint">
          {who(answer.by)}
          {answer.for && answer.for.toLowerCase() !== answer.by.toLowerCase() && ` for ${who(answer.for)}`}
          {answer.at && (
            <>
              {" · "}
              <Ago at={answer.at} />
            </>
          )}
          <ChevronRight className="size-3.5" aria-hidden />
        </span>
        <span className="col-start-2 col-end-4 truncate text-muted-foreground">
          {verdictOf(answer)}
          {answer.text && ` · “${answer.text}”`}
        </span>
      </button>
    );
  }

  const facts: [string, string][] = [];
  if (ask.happens) facts.push(["What happens", ask.happens]);
  if (ask.why) facts.push(["Why now", ask.why]);
  if (ask.undo) facts.push(["To undo", ask.undo]);
  const waitsOnMe = mine && !answer;
  const pickedCount = picked.length;

  return (
    <div
      data-ask={ask.id}
      className={cn("@container mt-1.5 max-w-2xl rounded-lg border bg-surface", waitsOnMe ? "border-yellow/40" : "border-border")}
    >
      <div className="px-3 pt-2.5 pb-2.5">
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-micro">
          <Icon className={cn("size-3.5", waitsOnMe ? "text-yellow" : "text-faint")} />
          <span className={waitsOnMe ? "font-medium text-yellow" : "text-muted-foreground"}>
            {heading(ask, mine, who(ask.to))}
          </span>
          {ask.recommendsApprove && (
            <>
              <span className="text-faint">·</span>
              <span className="text-accent">recommended</span>
            </>
          )}
          {answer && (
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-expanded
              aria-label="Fold"
              className="ml-auto rounded text-faint hover:text-text"
            >
              <ChevronDown className="size-3.5" />
            </button>
          )}
        </div>
        <p className="mt-1 text-body font-medium text-text">{ask.question}</p>
        {facts.length > 0 && (
          // Each fact is a paragraph with its label run in, so it wraps as
          // text does at any width, with no column to squeeze it.
          <div className="mt-1.5 space-y-1 text-label text-text">
            {facts.map(([label, value]) => (
              <p key={label}>
                <span className="font-medium text-muted-foreground">{label}</span> {value}
              </p>
            ))}
          </div>
        )}
        {ask.link && <AskLink link={ask.link} onOpenMemory={onOpenMemory} />}
        {ask.kind === "choose" && (
          <div
            role={ask.multiple ? "group" : "radiogroup"}
            aria-label={ask.question}
            className="mt-2 flex flex-col overflow-hidden rounded-md border border-border bg-bg"
          >
            {ask.options.map((o, i) => {
              const on = answer ? answer.choices.includes(o.id) : picked.includes(o.id);
              return (
                <label
                  key={o.id}
                  className={cn(
                    "flex items-start gap-2.5 px-2.5 py-1.5",
                    i > 0 && "border-t border-border",
                    on && "bg-accent-soft/40",
                    !answer && "cursor-pointer",
                  )}
                >
                  <input
                    type={ask.multiple ? "checkbox" : "radio"}
                    name={`ask-${ask.id}`}
                    checked={on}
                    disabled={Boolean(answer)}
                    onChange={() =>
                      setPicked((p) => (ask.multiple ? (p.includes(o.id) ? p.filter((x) => x !== o.id) : [...p, o.id]) : [o.id]))
                    }
                    className="mt-[3px] size-3.5 flex-shrink-0 accent-[var(--accent)]"
                  />
                  {/* The option is one sentence, its number then its text,
                      wrapping as text. Under it, whether it's recommended and
                      its detail, so neither breaks the sentence. */}
                  <span className="min-w-0 flex-1 text-label">
                    <span className="text-text">
                      <span className="tabular text-faint">{o.id}.</span> {o.label}
                    </span>
                    {(o.detail || ask.recommend.includes(o.id)) && (
                      <span className="mt-0.5 block text-micro text-muted-foreground">
                        {ask.recommend.includes(o.id) && <span className="text-accent">Recommended</span>}
                        {ask.recommend.includes(o.id) && o.detail && " · "}
                        {o.detail}
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 border-t border-border px-3 py-1.5">
        {answer ? (
          <div className="min-w-0 flex-1 text-label">
            <p className="text-text">
              <Verdict answer={answer} />
              <span className="text-muted-foreground">
                {" · "}
                {who(answer.by)}
                {answer.for && answer.for.toLowerCase() !== answer.by.toLowerCase() && `, for ${who(answer.for)}`}
              </span>
              {answer.at && (
                <>
                  {" "}
                  <Ago at={answer.at} className="text-micro text-faint" />
                </>
              )}
            </p>
            {answer.text && <p className="mt-0.5 text-muted-foreground">“{answer.text}”</p>}
          </div>
        ) : (
          <form
            className="flex min-w-0 flex-1 flex-wrap items-start gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              void send(ask.kind === "approve" ? "approved" : undefined);
            }}
          >
            {ask.kind === "question" ? (
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    void send();
                  }
                }}
                rows={2}
                placeholder={mine ? "Your answer" : `Answer for ${who(ask.to)}`}
                aria-label="Your answer"
                className="min-h-[3.25rem] min-w-0 flex-1 resize-y rounded-md border border-border2 bg-bg px-2 py-1 text-label text-text outline-none placeholder:text-faint focus:border-accent"
              />
            ) : (
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={mine ? "Add a note (optional)" : `Answer for ${who(ask.to)} (optional note)`}
                aria-label="Note"
                className="h-7 min-w-0 flex-1 basis-40 rounded-md border border-border2 bg-bg px-2 text-label text-text outline-none placeholder:text-faint focus:border-accent"
              />
            )}
            <span className="flex flex-shrink-0 items-center gap-1.5">
              {ask.kind === "approve" ? (
                <>
                  <Button type="submit" size="xs" variant={mine ? "default" : "outline"} disabled={busy}>
                    <Check className="size-3.5" /> Approve
                  </Button>
                  <Button type="button" size="xs" variant="ghost" disabled={busy} onClick={() => void send("declined")}>
                    Decline
                  </Button>
                </>
              ) : (
                <Button
                  type="submit"
                  size="xs"
                  variant={mine ? "default" : "outline"}
                  disabled={busy || (ask.kind === "question" ? !note.trim() : pickedCount === 0)}
                >
                  {ask.kind === "choose" && ask.multiple && pickedCount > 0 ? `Send ${pickedCount}` : "Send"}
                </Button>
              )}
            </span>
          </form>
        )}
        {error && (
          <span role="alert" className="w-full text-micro text-red">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}

/** What was decided, under the open card. The options above already show
 *  which were picked, ticked, so a pick is named by its numbers alone. */
function Verdict({ answer }: { answer: AskAnswer }) {
  const declined = answer.kind === "approve" && answer.decision === "declined";
  const Mark = declined ? X : Check;
  const ids = answer.choices;
  const said =
    answer.kind === "choose" && ids.length > 0
      ? `Chose ${ids.length > 1 ? `${ids.slice(0, -1).join(", ")} and ${ids[ids.length - 1]}` : ids[0]}`
      : verdictOf(answer);
  return (
    <span className="font-medium text-text">
      <Mark className={cn("mr-1 inline size-3.5 align-[-2px]", declined ? "text-red" : "text-green")} aria-hidden />
      {said}
    </span>
  );
}
