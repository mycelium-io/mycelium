// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { history, defaultKeymap, historyKeymap } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { indentUnit } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap, placeholder as placeholderText } from "@codemirror/view";
import { codeHighlighting, sourceHighlighting } from "@/lib/editor/highlight";
import { livePreview } from "@/lib/editor/live-preview";
import { markdownKeys } from "@/lib/editor/markdown-keys";
import { pasteAsMarkdown } from "@/lib/editor/paste-html";

/** What a host can do with the editor it holds. */
export interface MarkdownEditorHandle {
  readonly view: EditorView | null;
  focus: () => void;
  getValue: () => string;
}

interface Props {
  /** Read once, when the editor is built; it owns the text after that. */
  initialValue: string;
  onChange?: (text: string) => void;
  /** The plain markdown, with nothing drawn. */
  sourceMode?: boolean;
  placeholder?: string;
  /** ⌘/Ctrl-click on a `[[link]]` opens it. */
  onOpenLink?: (key: string) => void;
  extraExtensions?: Extension[];
  className?: string;
}

/**
 * A memory's markdown, edited in place: CodeMirror 6 with GitHub-flavored
 * markdown, Live Preview (unless `sourceMode`), the keys an Obsidian user
 * expects, code highlighted in its fence's language, and rich text pasted as
 * markdown. The text is always the markdown typed; nothing is rewritten.
 */
export const MarkdownEditor = forwardRef<MarkdownEditorHandle, Props>(function MarkdownEditor(
  { initialValue, onChange, sourceMode = false, placeholder, onOpenLink, extraExtensions = [], className },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changed = useRef(onChange);
  const openLink = useRef(onOpenLink);
  useEffect(() => {
    changed.current = onChange;
    openLink.current = onOpenLink;
  }, [onChange, onOpenLink]);

  useImperativeHandle(ref, () => ({
    get view() {
      return view.current;
    },
    focus: () => view.current?.focus(),
    getValue: () => view.current?.state.doc.toString() ?? "",
  }));

  useEffect(() => {
    if (!host.current) return;
    const extensions: Extension[] = [
      markdownKeys(),
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      markdown({ base: markdownLanguage, codeLanguages: languages }),
      indentUnit.of("  "),
      EditorView.lineWrapping,
      codeHighlighting(),
      pasteAsMarkdown,
      ...(placeholder ? [placeholderText(placeholder)] : []),
      ...(sourceMode ? [sourceHighlighting()] : [livePreview()]),
      EditorView.domEventHandlers({
        mousedown(event) {
          const link = (event.target as HTMLElement).closest?.(".cm-md-wikilink");
          const key = link?.getAttribute("data-key");
          if (!key || !(event.metaKey || event.ctrlKey) || !openLink.current) return false;
          event.preventDefault();
          openLink.current(key);
          return true;
        },
      }),
      ...extraExtensions,
      EditorView.updateListener.of((u) => {
        if (u.docChanged) changed.current?.(u.state.doc.toString());
      }),
    ];
    const editor = new EditorView({
      state: EditorState.create({ doc: initialValue, extensions }),
      parent: host.current,
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once; a host that needs a different editor gives it a new `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={host} className={className} />;
});
