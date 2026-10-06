// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { redo, undo } from "@codemirror/commands";
import { Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { MarkdownEditor, type MarkdownEditorHandle } from "@fedoup/markdown-editor";
import {
  Bold,
  Code,
  Eye,
  FileCode2,
  FileInput,
  Heading,
  History,
  Italic,
  Link2,
  List,
  ListOrdered,
  ListTodo,
  Maximize2,
  Minimize2,
  Minus,
  PenLine,
  Redo2,
  SquareCode,
  Strikethrough,
  Table,
  TextQuote,
  Undo2,
  Unlink,
  type LucideIcon,
} from "lucide-react";
import { WikilinkDropdown } from "@/components/wikilink-dropdown";
import { MarkdownContent } from "@/components/markdown-content";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useIsMac } from "@/lib/client-hooks";
import type { MemoryDraft } from "@/lib/memory-drafts";
import { fmtAgo } from "@/lib/metrics-format";
import {
  codeBlock,
  cycleHeading,
  draftLinks,
  insertBlock,
  TABLE_TEMPLATE,
  textStats,
  toggleLinePrefix,
  toggleWrap,
} from "@/lib/markdown-format";
import { headingGutter } from "@/lib/heading-gutter";
import { filterWikilinkCandidates, wikilinkDetector, type WikilinkMatch } from "@/lib/wikilink-completions";
import { cn } from "@/lib/utils";

/** Live Preview (markdown renders as it's typed), the plain source, or the
 *  body exactly as readers will see it. */
export type BodyMode = "write" | "source" | "preview";

/**
 * Where the cursor was, kept by the host so it outlives the editor: switching
 * mode or going full screen builds a new editor, which puts it back.
 */
export interface BodyCursor {
  get: () => { anchor: number; head: number } | null;
  set: (anchor: number, head: number) => void;
}

/** A host's `BodyCursor`, stable for the host's life. */
export function useBodyCursor(): BodyCursor {
  const [cursor] = useState<BodyCursor>(() => {
    let at: { anchor: number; head: number } | null = null;
    return {
      get: () => at,
      set: (anchor, head) => {
        at = { anchor, head };
      },
    };
  });
  return cursor;
}

interface Props {
  editorRef: React.RefObject<MarkdownEditorHandle | null>;
  /** The host's copy of the text: a new editor (mode, full screen, `generation`) starts from it. */
  value: string;
  onChange: (text: string) => void;
  cursor: BodyCursor;
  mode: BodyMode;
  onModeChange: (mode: BodyMode) => void;
  /** Every memory key in the room, for `[[` completion and the preview's links. */
  keys: string[];
  /** The keys `![[` may embed; defaults to all of them. */
  expandableKeys?: string[];
  placeholder?: string;
  autoFocus?: boolean;
  /** Bump to rebuild the editor from `value`, e.g. after restoring a draft. */
  generation?: number;
  /** Opens a memory a preview link points at. */
  onNavigate?: (key: string) => void;
  className?: string;
  /** Sizes the scrolling area under the toolbar. */
  bodyClassName?: string;
}

type Command = {
  label: string;
  icon: LucideIcon;
  /** CodeMirror key spelling ("Mod-b"), also shown in the button's tooltip. */
  keys?: string;
  run: (view: EditorView) => void;
};

const GROUPS: Command[][] = [
  [
    { label: "Heading", icon: Heading, keys: "Mod-Alt-h", run: cycleHeading },
    { label: "Bold", icon: Bold, keys: "Mod-b", run: (v) => toggleWrap(v, "**", "**", "bold") },
    { label: "Italic", icon: Italic, keys: "Mod-i", run: (v) => toggleWrap(v, "_", "_", "italic") },
    { label: "Strikethrough", icon: Strikethrough, keys: "Mod-Shift-x", run: (v) => toggleWrap(v, "~~", "~~", "struck") },
    { label: "Inline code", icon: Code, keys: "Mod-e", run: (v) => toggleWrap(v, "`", "`", "code") },
  ],
  [
    { label: "Bulleted list", icon: List, keys: "Mod-Shift-8", run: (v) => toggleLinePrefix(v, "bullet") },
    { label: "Numbered list", icon: ListOrdered, keys: "Mod-Shift-7", run: (v) => toggleLinePrefix(v, "number") },
    { label: "Checklist", icon: ListTodo, keys: "Mod-Shift-9", run: (v) => toggleLinePrefix(v, "task") },
    { label: "Quote", icon: TextQuote, keys: "Mod-Shift-.", run: (v) => toggleLinePrefix(v, "quote") },
  ],
  [
    { label: "Link to a memory", icon: Link2, keys: "Mod-Shift-k", run: (v) => toggleWrap(v, "[[", "]]", "") },
    { label: "Code block", icon: SquareCode, keys: "Mod-Alt-c", run: codeBlock },
    { label: "Table", icon: Table, run: (v) => insertBlock(v, TABLE_TEMPLATE, 2, 8) },
    { label: "Divider", icon: Minus, run: (v) => insertBlock(v, "---") },
  ],
];

const HISTORY: Command[] = [
  { label: "Undo", icon: Undo2, keys: "Mod-z", run: (v) => void undo(v) },
  { label: "Redo", icon: Redo2, keys: "Mod-Shift-z", run: (v) => void redo(v) },
];

const MODES: { mode: BodyMode; label: string; icon: LucideIcon; hint: string }[] = [
  { mode: "write", label: "Write", icon: PenLine, hint: "Markdown renders as you type" },
  { mode: "source", label: "Source", icon: FileCode2, hint: "The plain markdown" },
  { mode: "preview", label: "Preview", icon: Eye, hint: "As readers will see it" },
];

/** "Mod-Shift-x" → "⌘⇧X" on a Mac, "Ctrl+Shift+X" elsewhere. */
function spellKeys(keys: string, mac: boolean): string {
  const parts = keys.split("-");
  const key = parts.pop() ?? "";
  const names: Record<string, [string, string]> = {
    Mod: ["⌘", "Ctrl"],
    Shift: ["⇧", "Shift"],
    Alt: ["⌥", "Alt"],
  };
  const mods = parts.map((p) => names[p]?.[mac ? 0 : 1] ?? p);
  return [...mods, key.toUpperCase()].join(mac ? "" : "+");
}

/**
 * A memory's body: the Live Preview editor with a formatting toolbar, `[[`
 * completion, three ways to look at it (write, source, preview) and a count of
 * what's written. The new-memory dialog and the edit screen both write through
 * it, so they format, link and preview the same way.
 */
export function MemoryBodyEditor({
  editorRef,
  value: text,
  onChange,
  cursor,
  mode,
  onModeChange,
  keys,
  expandableKeys,
  placeholder,
  autoFocus,
  generation = 0,
  onNavigate,
  className,
  bodyClassName,
}: Props) {
  const mac = useIsMac();

  const [wikilinkMatch, setWikilinkMatch] = useState<WikilinkMatch | null>(null);
  const candidates = useMemo(() => {
    if (!wikilinkMatch) return [];
    const pool = wikilinkMatch.sigil === "![[" ? (expandableKeys ?? keys) : keys;
    return filterWikilinkCandidates(pool, wikilinkMatch.query);
  }, [wikilinkMatch, keys, expandableKeys]);

  const applyWikilink = useCallback(
    (target: string) => {
      const view = editorRef.current?.view;
      if (!view || !wikilinkMatch) return;
      const insert = `${wikilinkMatch.sigil}${target}]]`;
      // Through the live cursor, so a keystroke landing after the match was
      // made isn't stranded behind the inserted link.
      const to = Math.max(view.state.selection.main.head, wikilinkMatch.from);
      view.dispatch({
        changes: { from: wikilinkMatch.from, to, insert },
        selection: { anchor: wikilinkMatch.from + insert.length },
      });
      setWikilinkMatch(null);
      view.focus();
    },
    [editorRef, wikilinkMatch],
  );

  // Built once per editor: a new array would reconfigure CodeMirror mid-edit.
  // Everything it closes over is a ref or a stable setter.
  const extensions = useMemo(
    () => [
      wikilinkDetector(setWikilinkMatch),
      headingGutter,
      Prec.high(
        keymap.of(
          // Undo and redo are CodeMirror's own keys already.
          GROUPS.flat()
            .filter((c) => c.keys)
            .map((c) => ({
              key: c.keys as string,
              preventDefault: true,
              run: (view: EditorView) => {
                c.run(view);
                return true;
              },
            })),
        ),
      ),
      EditorView.updateListener.of((u) => {
        if (!u.selectionSet && !u.docChanged) return;
        const sel = u.state.selection.main;
        cursor.set(sel.anchor, sel.head);
      }),
    ],
    [cursor],
  );

  // A fresh editor puts the cursor back where the last one left it.
  const editorKey = `${mode}:${generation}`;
  useEffect(() => {
    if (mode === "preview") return;
    const view = editorRef.current?.view;
    if (!view) return;
    const at = cursor.get();
    if (at) {
      const len = view.state.doc.length;
      view.dispatch({
        selection: { anchor: Math.min(at.anchor, len), head: Math.min(at.head, len) },
        scrollIntoView: true,
      });
    }
    if (autoFocus || at) view.focus();
    // Only when a new editor is built.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editorKey]);

  const run = (command: Command) => {
    const view = editorRef.current?.view;
    if (view) command.run(view);
  };

  const keySet = useMemo(() => new Set(keys), [keys]);
  const broken = useMemo(() => {
    const out = new Set<string>();
    for (const m of text.matchAll(/!?\[\[([^\]\n|#]+)/g)) if (!keySet.has(m[1].trim())) out.add(m[1].trim());
    return out;
  }, [text, keySet]);

  const stats = textStats(text);
  const formatting = mode !== "preview";

  return (
    <div
      className={cn(
        "@container flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-bg focus-within:border-border2",
        className,
      )}
    >
      {/* Wraps rather than scrolls, so no control is ever out of sight. */}
      <div className="flex flex-shrink-0 flex-wrap items-center gap-1 border-b border-border px-1.5 py-1">
        <div role="toolbar" aria-label="Formatting" className="flex min-w-0 flex-wrap items-center gap-y-0.5">
          {[...GROUPS, HISTORY].map((group, i) => (
            <div key={i} className="flex flex-shrink-0 items-center gap-0.5">
              {i > 0 && <span aria-hidden className="mx-1 h-4 w-px bg-border" />}
              {group.map((c) => (
                <Tooltip key={c.label} content={c.keys ? `${c.label}  ${spellKeys(c.keys, mac)}` : c.label}>
                  <button
                    type="button"
                    aria-label={c.label}
                    disabled={!formatting}
                    // Keep the editor's selection: a click on the bar must not blur it.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => run(c)}
                    className="flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text disabled:pointer-events-none disabled:opacity-35"
                  >
                    <c.icon className="size-3.5" />
                  </button>
                </Tooltip>
              ))}
            </div>
          ))}
        </div>
        <div role="radiogroup" aria-label="View" className="ml-auto flex flex-shrink-0 items-center rounded-md bg-hairline/60 p-0.5">
          {MODES.map((m) => (
            <Tooltip key={m.mode} content={m.hint}>
              <button
                type="button"
                role="radio"
                aria-checked={mode === m.mode}
                aria-label={m.label}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => mode !== m.mode && onModeChange(m.mode)}
                className={cn(
                  "flex h-6 items-center gap-1 rounded px-1.5 text-micro transition-colors",
                  mode === m.mode ? "bg-bg text-text shadow-sm" : "text-muted-foreground hover:text-text",
                )}
              >
                <m.icon className="size-3.5" />
                <span className="hidden @3xl:inline">{m.label}</span>
              </button>
            </Tooltip>
          ))}
        </div>
      </div>

      <div className={cn("min-h-0 flex-1 overflow-y-auto", bodyClassName)}>
        {mode === "preview" ? (
          text.trim() ? (
            <MarkdownContent
              className="contrast text-body leading-relaxed px-4 py-3"
              onLinkClick={onNavigate}
              brokenLinks={broken}
            >
              {text}
            </MarkdownContent>
          ) : (
            <p className="px-4 py-3 text-label text-faint">Nothing to preview yet.</p>
          )
        ) : (
          <MarkdownEditor
            key={editorKey}
            ref={editorRef}
            // Read once, when this editor is built; it owns the text after that.
            initialValue={text}
            sourceMode={mode === "source"}
            placeholder={placeholder}
            onChange={onChange}
            extraExtensions={extensions}
            // Room on the left for each heading's level (`heading-gutter.ts`).
            className={cn(
              "h-full min-h-[200px] w-full px-4 py-3 [&_.cm-content]:!pl-7",
              mode === "source" && "font-mono",
            )}
          />
        )}
      </div>

      <div className="flex flex-shrink-0 items-center gap-3 border-t border-border px-3 py-1 text-micro text-faint">
        <span className="min-w-0 truncate">
          Markdown · <span className="font-mono">[[</span> links a memory
          {expandableKeys && (
            <>
              , <span className="font-mono">![[</span> embeds one
            </>
          )}
        </span>
        <span className="ml-auto flex-shrink-0 tabular" aria-live="polite">
          {stats.words} {stats.words === 1 ? "word" : "words"}
          {stats.words > 0 && <> · {stats.minutes} min read</>}
        </span>
      </div>

      {typeof document !== "undefined" &&
        wikilinkMatch &&
        candidates.length > 0 &&
        createPortal(
          <WikilinkDropdown
            match={wikilinkMatch}
            candidates={candidates}
            onSelect={applyWikilink}
            onDismiss={() => setWikilinkMatch(null)}
          />,
          document.body,
        )}
    </div>
  );
}

/** Both editors' full-screen toggle and its ⌘⇧F / Esc handling, live while `enabled`. */
export function useFullscreen(enabled = true): [boolean, (next: boolean | ((on: boolean) => boolean)) => void] {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setOn((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
  useEffect(() => {
    if (!on || !enabled) return;
    // Esc leaves full screen before it does anything else (closing a dialog).
    // An open `[[` completion list takes Esc first: it listens on window in
    // the capture phase, ahead of this.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setOn(false);
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [on, enabled]);
  return [on, setOn];
}

/** The full-screen toggle both editors put in their header. */
export function FullscreenButton({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  const mac = useIsMac();
  const label = on ? "Exit full screen" : "Full screen";
  return (
    <Tooltip content={`${label}  ${mac ? "⌘⇧F" : "Ctrl+Shift+F"}`}>
      <button
        type="button"
        aria-label={label}
        aria-pressed={on}
        onClick={onToggle}
        className="grid size-7 flex-shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
      >
        {on ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
      </button>
    </Tooltip>
  );
}

/** Offers back an edit left unsaved here earlier. */
export function DraftBanner({
  draft,
  note,
  onRestore,
  onDiscard,
}: {
  draft: MemoryDraft;
  /** What a restore would need to know, e.g. that the memory moved on since. */
  note?: string;
  onRestore: () => void;
  onDiscard: () => void;
}) {
  return (
    <div
      role="status"
      className="flex flex-shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-accent/25 bg-accent-soft/50 px-5 py-2 text-label text-text"
    >
      <History className="size-3.5 flex-shrink-0 text-accent" />
      <span className="min-w-0 flex-1">
        You left unsaved changes here {fmtAgo(draft.savedAt)}
        {note && <span className="text-muted-foreground"> ({note})</span>}.
      </span>
      <Button variant="ghost" size="sm" onClick={onDiscard}>
        Discard
      </Button>
      <Button variant="outline" size="sm" onClick={onRestore}>
        Restore
      </Button>
    </div>
  );
}

/** The links a body makes as it's written, with the ones that go nowhere called out. */
export function DraftLinks({
  text,
  keys,
  onNavigate,
}: {
  text: string;
  keys: ReadonlySet<string>;
  onNavigate?: (key: string) => void;
}) {
  const links = useMemo(() => draftLinks(text, keys), [text, keys]);
  if (links.length === 0) return null;
  const missing = links.filter((l) => !l.exists).length;
  return (
    <section className="flex flex-col gap-1">
      <h3 className="flex items-center gap-1.5 text-micro font-medium text-faint">
        Links
        <span className="font-normal tabular">{links.length}</span>
        {missing > 0 && <span className="font-normal text-yellow">· {missing} not found</span>}
      </h3>
      {links.map((l) => {
        const Icon = l.exists ? (l.embed ? FileInput : Link2) : Unlink;
        const row = (
          <>
            <Icon className={cn("size-3 flex-shrink-0", l.exists ? "text-faint" : "text-yellow")} />
            <span className="min-w-0 truncate font-mono">{l.key}</span>
            {l.embed && <span className="ml-auto flex-shrink-0 text-[10px] text-faint">embed</span>}
          </>
        );
        return l.exists && onNavigate ? (
          <button
            key={`${l.embed}:${l.key}`}
            type="button"
            onClick={() => onNavigate(l.key)}
            className="-mx-1.5 flex min-w-0 items-center gap-1.5 rounded px-1.5 py-0.5 text-left text-micro text-accent transition-colors hover:bg-hairline"
          >
            {row}
          </button>
        ) : (
          <div
            key={`${l.embed}:${l.key}`}
            title={l.exists ? undefined : "No memory has this key yet"}
            className={cn("flex min-w-0 items-center gap-1.5 py-0.5 text-micro", l.exists ? "text-text" : "text-yellow")}
          >
            {row}
          </div>
        );
      })}
    </section>
  );
}
