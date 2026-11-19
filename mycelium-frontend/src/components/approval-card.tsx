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
  SkipForward,
  X,
} from "lucide-react";
import { answerAsk } from "@/lib/api";
import { MarkdownContent } from "@/components/markdown-content";
import { askLine, linkKind, verdictOf, type ApprovalAsk, type AskAnswer, type AskKind, type Decision } from "@/lib/approvals";
import { useCurrentUser } from "@/components/current-user";
import { nameOf, useNames } from "@/lib/people";
import { useRoomRevalidate } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { Button } from "@/components/ui/button";
import { SendPlaneIcon } from "@/components/send-plane-icon";
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

  /** `none` answers a choose with none of its options, whatever is ticked.
   *  `skip` answers nothing: the person isn't answering this one, and only a
   *  note goes with it (a question's text box is its answer, so not that). */
  const send = async (decision?: Decision, none = false, skip = false) => {
    if (busy || !me) return;
    const text = skip && ask.kind === "question" ? null : note.trim() || null;
    if (!skip && ask.kind === "question" && !text) return;
    if (!skip && ask.kind === "choose" && !none && (picked.length === 0 || (!ask.multiple && picked.length > 1))) return;
    setBusy(true);
    setError(null);
    const choices =
      ask.kind === "choose" && !none && !skip ? ask.options.filter((o) => picked.includes(o.id)).map((o) => o.id) : [];
    try {
      await answerAsk(roomName, ask.id, {
        by: me,
        ...(skip ? { skipped: true } : {}),
        ...(decision ? { decision } : {}),
        ...(ask.kind === "choose" && !skip ? { choices } : {}),
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
        skipped: skip,
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
    return (
      <button
        type="button"
        data-ask={ask.id}
        onClick={() => setOpen(true)}
        aria-expanded={false}
        className="mt-1.5 grid w-full max-w-2xl grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-left text-label hover:bg-hairline"
      >
        <VerdictMark answer={answer} className="self-center" />
        <span className="truncate text-text">{askLine(ask.question)}</span>
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
  const canSend = ask.kind === "question" ? Boolean(note.trim()) : ask.kind === "choose" ? pickedCount > 0 : true;

  return (
    <div
      data-ask={ask.id}
      // A hairline like the app's other surfaces: the yellow label and icon say
      // it waits on you, so the border doesn't shout it in the chat too.
      className="@container mt-1.5 max-w-2xl rounded-lg border border-border bg-surface"
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
        {/* The first paragraph is the question; what follows it is its detail. */}
        <MarkdownContent
          className="markdown-ui mt-1 text-body text-text [&>*:first-child]:font-medium"
          onLinkClick={onOpenMemory}
        >
          {ask.question}
        </MarkdownContent>
        {facts.length > 0 && (
          // Each fact is a paragraph with its label run in, so it wraps as
          // text does at any width, with no column to squeeze it.
          <div className="mt-1.5 space-y-1 text-label text-text">
            {facts.map(([label, value]) => (
              <div key={label}>
                <span className="font-medium text-muted-foreground">{label}</span>{" "}
                {/* The label runs into the first paragraph; a list after it
                    starts on a line of its own. */}
                <MarkdownContent className="markdown-ui inline [&>p:first-child]:inline" onLinkClick={onOpenMemory}>
                  {value}
                </MarkdownContent>
              </div>
            ))}
          </div>
        )}
        {ask.link && <AskLink link={ask.link} onOpenMemory={onOpenMemory} />}
        {ask.kind === "choose" && (
          <div
            role={ask.multiple ? "group" : "radiogroup"}
            aria-label={askLine(ask.question)}
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
                      <span className="tabular text-faint">{o.id}.</span>{" "}
                      <MarkdownContent inline onLinkClick={onOpenMemory}>
                        {o.label}
                      </MarkdownContent>
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
      <div
        className={cn(
          "flex flex-wrap items-center gap-1.5 px-3",
          // The answer field is a frame of its own, so no divider above it.
          answer ? "min-h-9 border-t border-border py-1.5" : "pb-3",
        )}
      >
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
          // One field, shaped like the room's composer: the note (or a
          // question's answer) on top, then a bar inside it with the other
          // answers and Skip on the left and the main answer on the right,
          // where the composer's send is.
          <form
            className="w-full rounded-lg border border-border2 bg-bg transition-colors focus-within:border-accent"
            onSubmit={(e) => {
              e.preventDefault();
              void send(ask.kind === "approve" ? "approved" : undefined);
            }}
          >
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                // ⌘↵ sends what was typed or picked. On an approve the note is
                // as likely a Decline's, so a yes or no is only ever a click.
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && ask.kind !== "approve" && canSend) {
                  e.preventDefault();
                  void send();
                }
              }}
              rows={ask.kind === "question" ? 2 : 1}
              placeholder={
                ask.kind === "question" ? (mine ? "Your answer" : `Answer for ${who(ask.to)}`) : "Add a note"
              }
              aria-label={ask.kind === "question" ? "Your answer" : "Note"}
              className="block w-full resize-none bg-transparent px-2.5 py-2 text-label text-text outline-none placeholder:text-faint"
            />
            <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
              {ask.kind === "approve" && (
                <Button type="button" size="xs" variant="outline" disabled={busy} onClick={() => void send("declined")}>
                  <X className="size-3.5" /> Decline
                </Button>
              )}
              {/* None of them is an answer too, said on purpose rather than by
                  sending with nothing ticked. The note goes with it. */}
              {ask.kind === "choose" && (
                <Button type="button" size="xs" variant="ghost" disabled={busy} onClick={() => void send(undefined, true)}>
                  None of these
                </Button>
              )}
              {/* Not an answer: the agent carries on with its own judgment. */}
              <Button
                type="button"
                size="xs"
                variant="ghost"
                disabled={busy}
                onClick={() => void send(undefined, false, true)}
                className="text-muted-foreground"
              >
                Skip
              </Button>
              <span className="ml-auto">
                {ask.kind === "question" ? (
                  <button
                    type="submit"
                    disabled={busy || !canSend}
                    aria-label="Send"
                    className="flex size-7 items-center justify-center rounded-md text-accent transition-colors hover:bg-accent-soft disabled:text-faint disabled:hover:bg-transparent"
                  >
                    <SendPlaneIcon className="size-4" />
                  </button>
                ) : (
                  <Button type="submit" size="xs" variant={mine ? "default" : "outline"} disabled={busy || !canSend}>
                    {ask.kind === "approve" ? (
                      <>
                        <Check className="size-3.5" /> Approve
                      </>
                    ) : ask.multiple && pickedCount > 0 ? (
                      `Send ${pickedCount}`
                    ) : (
                      "Send"
                    )}
                  </Button>
                )}
              </span>
            </div>
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
  const ids = answer.choices;
  const said =
    answer.kind === "choose" && ids.length > 0
      ? `Chose ${ids.length > 1 ? `${ids.slice(0, -1).join(", ")} and ${ids[ids.length - 1]}` : ids[0]}`
      : verdictOf(answer);
  return (
    <span className="font-medium text-text">
      <VerdictMark answer={answer} className="mr-1 inline align-[-2px]" />
      {said}
    </span>
  );
}

/** A check for an answer, a cross for a declined approve, and a quiet skip mark
 *  for an ask that was skipped rather than answered. */
function VerdictMark({ answer, className }: { answer: AskAnswer; className?: string }) {
  if (answer.skipped) return <SkipForward className={cn("size-3.5 text-faint", className)} aria-hidden />;
  const declined = answer.kind === "approve" && answer.decision === "declined";
  const Mark = declined ? X : Check;
  return <Mark className={cn("size-3.5", declined ? "text-red" : "text-green", className)} aria-hidden />;
}
