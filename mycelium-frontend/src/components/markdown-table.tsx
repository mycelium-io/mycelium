// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";

/** A cell's alignment, as Markdown writes it under its column's header. */
function rule(cell: Element): string {
  const align = (cell as HTMLElement).style.textAlign;
  if (align === "center") return ":---:";
  if (align === "right") return "---:";
  if (align === "left") return ":---";
  return "---";
}

/** A rendered table back as Markdown: the text of each cell, with its
 *  column's alignment kept, and any `|` in a cell escaped. */
export function tableToMarkdown(table: HTMLTableElement): string {
  const rows = [...table.querySelectorAll("tr")].map((tr) =>
    [...tr.querySelectorAll("th, td")].map((cell) => (cell.textContent ?? "").trim().replace(/\|/g, "\\|")),
  );
  if (rows.length === 0) return "";
  const line = (cells: string[]) => `| ${cells.join(" | ")} |`;
  const head = table.querySelector("tr");
  const rules = head ? [...head.querySelectorAll("th, td")].map(rule) : rows[0].map(() => "---");
  return [line(rows[0]), line(rules), ...rows.slice(1).map(line)].join("\n");
}

/**
 * A Markdown table in a message or a memory: in a rounded frame that scrolls
 * sideways when the table is wider than the pane, with a Copy button that
 * shows on hover and copies it back as Markdown.
 */
export function MarkdownTable({ children }: { children?: ReactNode }) {
  const table = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  const copy = () => {
    if (!table.current) return;
    void navigator.clipboard?.writeText(tableToMarkdown(table.current)).then(() => setCopied(true));
  };
  return (
    <div className="md-table">
      <div className="md-table-frame">
        <table ref={table}>{children}</table>
      </div>
      <button type="button" onClick={copy} className="md-table-copy" aria-label="Copy table as Markdown">
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
