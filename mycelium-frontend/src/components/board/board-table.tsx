// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { attentionFilterOf, type LiveItem } from "@/lib/board/item";
import type { FieldSchema } from "@/lib/board/schema";
import { KindIcon, openableThread } from "./board-cells";

interface Props {
  items: LiveItem[];
  schema: FieldSchema[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** An edited cell writes one frontmatter field back to the markdown. */
  onEdit: (item: LiveItem, field: string, value: unknown) => void;
  /** The board's shared tick, so every view drains a lease at the same moment. */
  now: number;
  /** Sort is a view property, so a header click changes the view, not the data. */
  sort: { field: string; dir: "asc" | "desc" };
  onSort: (field: string) => void;
  onOpenThread?: (episode: string) => void;
}

/** Columns are capped so a wide schema still reads; the rest stay filterable. */
const MAX_COLUMNS = 7;

/** A thread's identity is not a column: the id is noise and the URN is worse.
 *  The thread is opened by the row, not read as a cell. */
const HIDDEN_COLUMNS = new Set(["choices", "episode", "thread"]);

export function BoardTable({ items, schema, now, selectedId, onSelect, onEdit, sort, onSort, onOpenThread }: Props) {
  const columns = schema.filter(f => !HIDDEN_COLUMNS.has(f.name)).slice(0, MAX_COLUMNS);

  return (
    <div className="min-w-0 overflow-auto px-5 py-4">
      <table className="w-full min-w-[900px] border-separate border-spacing-0 text-label">
        <thead>
          <tr>
            <th className="sticky top-0 z-10 border-b border-border bg-bg px-2 py-1.5 text-left font-medium text-muted-foreground">
              <span className="font-mono text-micro">Row</span>
            </th>
            {columns.map(field => (
              <th
                key={field.name}
                onClick={() => onSort(field.name)}
                className="sticky top-0 z-10 cursor-pointer border-b border-border bg-bg px-2 py-1.5 text-left font-medium text-muted-foreground hover:text-text"
                title={`${field.type} · filled in ${field.filled}/${field.total} rows`}
              >
                <span className="inline-flex items-center gap-1.5">
                  <span className="font-mono text-micro">{field.label}</span>
                  <span className="rounded bg-hairline px-1 font-mono text-micro text-faint">{field.type}</span>
                  {sort.field === field.name && (
                    <ChevronDown
                      className={cn("size-3 text-accent transition-transform", sort.dir === "asc" && "rotate-180")}
                    />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map(item => (
            <tr
              key={item.id}
              onClick={() => {
                onSelect(item.id);
                const episode = openableThread(item);
                if (episode) onOpenThread?.(episode);
              }}
              className={cn(
                "group cursor-pointer",
                item.id === selectedId ? "bg-elevated" : "hover:bg-hairline",
                attentionFilterOf(item, now) === "resolved" && "opacity-65",
              )}
            >
              <td className="max-w-[380px] border-b border-hairline px-2 py-1.5">
                <span className="flex items-center gap-2">
                  <KindIcon item={item} />
                  <span className="min-w-0 flex-1 truncate text-text">{item.title}</span>
                </span>
              </td>
              {columns.map(field => (
                <td key={field.name} className="border-b border-hairline px-1 py-1 align-middle">
                  <Cell item={item} field={field} onEdit={value => onEdit(item, field.name, value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {items.length === 0 && (
        <p className="px-2 py-8 text-center text-label text-muted-foreground">
          No rows match this view.
        </p>
      )}
    </div>
  );
}

/**
 * One cell, rendered and edited by inferred type. A select edits against the
 * vocabulary the namespace already uses, which is why editing here can't invent
 * a value the rest of the room has never seen.
 */
function Cell({
  item,
  field,
  onEdit,
}: {
  item: LiveItem;
  field: FieldSchema;
  onEdit: (value: unknown) => void;
}) {
  const raw = item.fields[field.name];
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const empty = raw === null || raw === undefined || raw === "";

  if (field.type === "select" || field.type === "handle") {
    return (
      <div ref={wrap} className="relative">
        <button
          onClick={e => {
            e.stopPropagation();
            setOpen(o => !o);
          }}
          className={cn(
            "flex w-full items-center gap-1 rounded px-1.5 py-0.5 text-left transition-colors hover:bg-surface",
            empty && "text-faint",
          )}
        >
          <span className="truncate font-mono text-micro">{empty ? "-" : String(raw)}</span>
          <ChevronDown className="ml-auto size-3 shrink-0 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
        {open && (
          <div className="absolute left-0 top-full z-30 mt-1 min-w-[160px] rounded-lg border border-border bg-paper p-1 shadow-lg">
            <p className="px-2 py-1 font-mono text-micro text-faint">
              {field.label} · {field.options.length} values in this namespace
            </p>
            {field.options.map(opt => (
              <button
                key={opt.value}
                onClick={e => {
                  e.stopPropagation();
                  onEdit(opt.value);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-label text-text transition-colors hover:bg-surface"
              >
                <span className="flex-1 truncate font-mono text-micro">{opt.value}</span>
                <span className="tabular text-micro text-faint">{opt.count}</span>
                {String(raw) === opt.value && <Check className="size-3 text-accent" />}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (field.type === "checkbox") {
    return (
      <button
        onClick={e => {
          e.stopPropagation();
          onEdit(raw !== true);
        }}
        className={cn(
          "flex size-4 items-center justify-center rounded border transition-colors",
          raw === true ? "border-accent bg-accent text-accent-fg" : "border-border2 hover:border-accent",
        )}
      >
        {raw === true && <Check className="size-3" />}
      </button>
    );
  }

  if (field.type === "tags") {
    const tags = Array.isArray(raw) ? raw.map(String) : empty ? [] : [String(raw)];
    return (
      <span className="flex flex-wrap gap-1">
        {tags.length === 0 && <span className="px-1.5 text-micro text-faint">-</span>}
        {tags.map(tag => (
          <span key={tag} className="rounded bg-surface px-1.5 font-mono text-micro text-muted-foreground">
            {tag}
          </span>
        ))}
      </span>
    );
  }

  if (field.type === "date") {
    return (
      <span className="px-1.5 font-mono text-micro text-muted-foreground">
        {empty ? "-" : new Date(String(raw)).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
      </span>
    );
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onClick={e => e.stopPropagation()}
        onBlur={() => {
          setEditing(false);
          if (draft !== String(raw ?? "")) onEdit(field.type === "number" ? Number(draft) : draft);
        }}
        onKeyDown={e => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-full rounded border border-accent/50 bg-bg px-1.5 py-0.5 font-mono text-micro text-text outline-none"
      />
    );
  }

  return (
    <button
      onClick={e => {
        e.stopPropagation();
        setDraft(empty ? "" : String(raw));
        setEditing(true);
      }}
      className={cn(
        "w-full truncate rounded px-1.5 py-0.5 text-left font-mono text-micro transition-colors hover:bg-surface",
        empty ? "text-faint" : "text-muted-foreground",
      )}
    >
      {empty ? "-" : String(raw)}
    </button>
  );
}
