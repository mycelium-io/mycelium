// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, useSyncExternalStore } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  FileText,
  ListChecks,
  MessageCircleQuestion,
  MessageSquarePlus,
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

/** MOCK: alternatives to the card's look in the chat, picked by `?ask=` in the
 *  URL. `box` is today's card; the rest are being compared. */
type AskStyle = "box" | "quiet" | "rule" | "tint";
const ASK_STYLES: readonly AskStyle[] = ["box", "quiet", "rule", "tint"];
const subscribeNever = () => () => {};
function useAskStyle(): AskStyle {
  return useSyncExternalStore(
    subscribeNever,
    () => {
      const v = new URLSearchParams(window.location.search).get("ask");
      return ASK_STYLES.find((s) => s === v) ?? "box";
    },
    () => "box",
  );
}

/** MOCK: alternatives to the answer controls, picked by `?ctl=`. */
type Controls = "now" | "a" | "b";
function useAskControls(): Controls {
  return useSyncExternalStore(
    subscribeNever,
    () => {
      const v = new URLSearchParams(window.location.search).get("ctl");
      return v === "a" || v === "b" ? v : "now";
    },
    () => "now",
  );
}

/**
 * MOCK: the answer controls, two ways.
 *
 * `a`: the answers first, left-aligned under the ask, where the eye already
 * is; a note opens from an icon; Skip sits apart at the right. A question's
 * answer is a field with its send arrow inside, as the room's composer has.
 *
 * `b`: one field shaped like the room's composer. The note (or a question's
 * answer) on top, and a bar inside it: the other answers and Skip on the
 * left, the main answer on the right, where the composer's send is.
 */
function AskControls({
  variant,
  kind,
  mine,
  note,
  setNote,
  busy,
  canSend,
  sendLabel,
  onSend,
  askedOf,
}: {
  variant: "a" | "b";
  kind: AskKind;
  mine: boolean;
  note: string;
  setNote: (v: string) => void;
  busy: boolean;
  canSend: boolean;
  sendLabel: string;
  onSend: (decision?: Decision, none?: boolean, skip?: boolean) => void;
  askedOf: string;
}) {
  const [noteOpen, setNoteOpen] = useState(false);
  const primary = () => onSend(kind === "approve" ? "approved" : undefined);
  const placeholder = kind === "question" ? (mine ? "Your answer" : `Answer for ${askedOf}`) : "Add a note";
  const field = (rows: number, autoFocus = false) => (
    <textarea
      value={note}
      onChange={(e) => setNote(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend) {
          e.preventDefault();
          primary();
        }
      }}
      rows={rows}
      autoFocus={autoFocus}
      placeholder={placeholder}
      aria-label={kind === "question" ? "Your answer" : "Note"}
      className="block w-full resize-none bg-transparent px-2.5 py-2 text-label text-text outline-none placeholder:text-faint"
    />
  );
  const sendArrow = (
    <button
      type="button"
      onClick={primary}
      disabled={busy || !canSend}
      aria-label="Send"
      className="flex size-7 items-center justify-center rounded-md text-accent transition-colors hover:bg-accent-soft disabled:text-faint disabled:hover:bg-transparent"
    >
      <SendPlaneIcon className="size-4" />
    </button>
  );
  const skip = (
    <Button type="button" size="xs" variant="ghost" disabled={busy} onClick={() => onSend(undefined, false, true)} className="text-muted-foreground">
      Skip
    </Button>
  );
  const decline = (
    <Button type="button" size="xs" variant="outline" disabled={busy} onClick={() => onSend("declined")}>
      <X className="size-3.5" /> Decline
    </Button>
  );
  const none = (
    <Button type="button" size="xs" variant="ghost" disabled={busy} onClick={() => onSend(undefined, true)}>
      None of these
    </Button>
  );
  const main =
    kind === "approve" ? (
      <Button type="button" size="xs" disabled={busy} onClick={primary}>
        <Check className="size-3.5" /> Approve
      </Button>
    ) : (
      <Button type="button" size="xs" disabled={busy || !canSend} onClick={primary}>
        {sendLabel}
      </Button>
    );

  if (variant === "a") {
    return (
      <div className="flex w-full flex-col gap-2">
        {kind === "question" && (
          // The answer is the field, so its send and Skip sit inside it.
          <div className="flex items-end rounded-lg border border-border2 bg-bg pr-1 pb-1 focus-within:border-accent">
            {field(2)}
            {skip}
            {sendArrow}
          </div>
        )}
        {noteOpen && (
          <div className="rounded-lg border border-border2 bg-bg focus-within:border-accent">{field(1, true)}</div>
        )}
        {kind !== "question" && <div className="flex items-center gap-1.5">
          {main}
          {kind === "approve" && decline}
          {kind === "choose" && none}
          <span className="ml-auto flex items-center gap-0.5">
            {!noteOpen && (
              <button
                type="button"
                onClick={() => setNoteOpen(true)}
                aria-label="Add a note"
                title="Add a note"
                className="flex size-7 items-center justify-center rounded-md text-faint transition-colors hover:bg-hairline hover:text-text"
              >
                <MessageSquarePlus className="size-4" />
              </button>
            )}
            {skip}
          </span>
        </div>}
      </div>
    );
  }
  return (
    <div className="w-full rounded-lg border border-border2 bg-bg focus-within:border-accent">
      {field(kind === "question" ? 2 : 1)}
      <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
        {kind === "approve" && decline}
        {kind === "choose" && none}
        {skip}
        <span className="ml-auto">{kind === "question" ? sendArrow : main}</span>
      </div>
    </div>
  );
}

/** The card's frame, its body's padding and its footer, per style. */
function frame(style: AskStyle, waitsOnMe: boolean) {
  switch (style) {
    case "quiet":
      // Today's card, with the yellow only on the label and icon.
      return { outer: "rounded-lg border border-border bg-surface", body: "px-3 pt-2.5 pb-2.5", foot: "border-t border-border px-3 py-1.5" };
    case "rule":
      // No box: a rule down its left edge, like a quote, on the chat itself.
      return {
        outer: cn("border-l-2", waitsOnMe ? "border-yellow/70" : "border-border2"),
        body: "pl-3 pt-0.5 pb-1.5",
        foot: "pl-3 pb-0.5",
      };
    case "tint":
      // No border: a faint fill, warm while it waits on you.
      return {
        outer: cn("rounded-lg", waitsOnMe ? "bg-yellow/[0.06]" : "bg-surface"),
        body: "px-3 pt-2.5 pb-1",
        foot: "px-3 pb-2.5 pt-1",
      };
    default:
      return {
        outer: cn("rounded-lg border bg-surface", waitsOnMe ? "border-yellow/40" : "border-border"),
        body: "px-3 pt-2.5 pb-2.5",
        foot: "border-t border-border px-3 py-1.5",
      };
  }
}

/** The answered card, folded to one row, per style. */
function foldedFrame(style: AskStyle): string {
  if (style === "rule") return "border-l-2 border-border2 pl-3 pr-0 hover:bg-hairline";
  if (style === "tint") return "rounded-lg bg-surface px-3 hover:bg-hairline";
  return "rounded-lg border border-border bg-surface px-3 hover:bg-hairline";
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
  const style = useAskStyle();
  const controls = useAskControls();
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
        className={cn(
          "mt-1.5 grid w-full max-w-2xl grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-2 py-1.5 text-left text-label",
          foldedFrame(style),
        )}
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
  const look = frame(style, waitsOnMe);
  const pickedCount = picked.length;

  return (
    <div
      data-ask={ask.id}
      className={cn("@container mt-1.5 max-w-2xl", look.outer)}
    >
      <div className={look.body}>
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
          "flex min-h-9 flex-wrap items-center gap-1.5",
          look.foot,
          // B's field is its own frame, so no divider above it.
          controls === "b" && !answer && "border-t-0 pt-0 pb-3",
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
        ) : controls !== "now" ? (
          <AskControls
            variant={controls}
            kind={ask.kind}
            mine={mine}
            note={note}
            setNote={setNote}
            busy={busy}
            canSend={ask.kind === "question" ? Boolean(note.trim()) : ask.kind === "choose" ? pickedCount > 0 : true}
            sendLabel={ask.kind === "choose" && ask.multiple && pickedCount > 0 ? `Send ${pickedCount}` : "Send"}
            onSend={(decision, none, skip) => void send(decision, none, skip)}
            askedOf={who(ask.to)}
          />
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
                <>
                  <Button
                    type="submit"
                    size="xs"
                    variant={mine ? "default" : "outline"}
                    disabled={busy || (ask.kind === "question" ? !note.trim() : pickedCount === 0)}
                  >
                    {ask.kind === "choose" && ask.multiple && pickedCount > 0 ? `Send ${pickedCount}` : "Send"}
                  </Button>
                  {/* None of them is an answer too, said on purpose rather
                      than by sending with nothing ticked. The note goes with it. */}
                  {ask.kind === "choose" && (
                    <Button type="button" size="xs" variant="ghost" disabled={busy} onClick={() => void send(undefined, true)}>
                      None of these
                    </Button>
                  )}
                </>
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
