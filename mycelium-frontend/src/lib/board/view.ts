// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A view is a filter, a grouping and a sort over the projected rows.
 *
 * The cockpit's "needs you" lens and a kanban grouped by `status` differ only in
 * this config, so the coordination surface is a saved view of the typed one
 * rather than a separate screen with its own rules.
 */

import {
  PRIORITY_ORDER,
  STATUS_ORDER,
  ageMinutes,
  arr,
  kindOf,
  lensOf,
  num,
  priorityOf,
  statusOf,
  str,
  type Lens,
  type LiveItem,
} from "./item";
import { fieldByName, humanize, type FieldSchema } from "./schema";

export type ViewMode = "cockpit" | "board" | "table" | "timeline" | "daily" | "docs";

export interface ViewConfig {
  mode: ViewMode;
  /** "all" is the firehose; the cockpit defaults to a single lens. */
  lens: Lens | "all";
  groupBy: string | null;
  sort: { field: string; dir: "asc" | "desc" };
  /** field name → allowed values; empty array means "no constraint". */
  filters: Record<string, string[]>;
  query: string;
  /** Rows the room resolved earlier auto-hide unless asked for. */
  showResolved: boolean;
}

export interface ItemGroup {
  key: string;
  label: string;
  items: LiveItem[];
}

export const DEFAULT_VIEW: ViewConfig = {
  mode: "cockpit",
  lens: "needs_you",
  groupBy: "kind",
  sort: { field: "priority", dir: "asc" },
  filters: {},
  query: "",
  showResolved: false,
};

/**
 * Presets, expressed as the same config a user edit produces. In a real build
 * each of these is a memory under `views/` — a saved view is room state like
 * anything else, so it syncs and is editable as markdown.
 */
export interface SavedView {
  slug: string;
  label: string;
  hint: string;
  config: ViewConfig;
}

export const SAVED_VIEWS: SavedView[] = [
  {
    slug: "needs-you",
    label: "Needs you",
    hint: "the steer-lens: open decisions, blocks, reviews",
    config: { ...DEFAULT_VIEW },
  },
  {
    slug: "in-flight",
    label: "In flight",
    hint: "claimed work, grouped by who holds it",
    config: { ...DEFAULT_VIEW, lens: "in_flight", groupBy: "owner", sort: { field: "updated", dir: "desc" } },
  },
  {
    slug: "by-status",
    label: "Kanban",
    hint: "every row, grouped by status",
    config: { ...DEFAULT_VIEW, mode: "board", lens: "all", groupBy: "status", showResolved: true },
  },
  {
    slug: "table",
    label: "Table",
    hint: "the namespace as typed data, inline-editable",
    config: { ...DEFAULT_VIEW, mode: "table", lens: "all", groupBy: null, showResolved: true },
  },
  {
    slug: "daily",
    label: "Daily log",
    hint: "what the room did, by day, in your own timezone",
    config: { ...DEFAULT_VIEW, mode: "daily", lens: "all", groupBy: null, showResolved: true },
  },
  {
    slug: "timeline",
    label: "Timeline",
    hint: "what moved, newest first",
    config: {
      ...DEFAULT_VIEW,
      mode: "timeline",
      lens: "all",
      groupBy: null,
      sort: { field: "updated", dir: "desc" },
      showResolved: true,
    },
  },
];

// ── Filtering ────────────────────────────────────────────────────────────────

function matchesQuery(item: LiveItem, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if (item.title.toLowerCase().includes(q)) return true;
  if (item.source.label.toLowerCase().includes(q)) return true;
  return Object.values(item.fields).some(v => {
    if (typeof v === "string") return v.toLowerCase().includes(q);
    if (Array.isArray(v)) return v.some(x => typeof x === "string" && x.toLowerCase().includes(q));
    return false;
  });
}

function fieldValues(item: LiveItem, name: string): string[] {
  const raw = item.fields[name];
  if (raw === null || raw === undefined || raw === "") return [];
  if (Array.isArray(raw)) return raw.map(String);
  return [String(raw)];
}

export function filterItems(items: LiveItem[], config: ViewConfig): LiveItem[] {
  return items.filter(item => {
    if (config.lens !== "all" && lensOf(item) !== config.lens) return false;
    if (!config.showResolved && config.lens === "all" && lensOf(item) === "resolved") return false;
    if (!matchesQuery(item, config.query)) return false;
    for (const [name, allowed] of Object.entries(config.filters)) {
      if (allowed.length === 0) continue;
      const values = fieldValues(item, name);
      if (!values.some(v => allowed.includes(v))) return false;
    }
    return true;
  });
}

// ── Sorting ──────────────────────────────────────────────────────────────────

function ordinal(item: LiveItem, field: string, now: number): number | string {
  if (field === "priority") return PRIORITY_ORDER.indexOf(priorityOf(item));
  if (field === "status") return STATUS_ORDER.indexOf(statusOf(item));
  if (field === "updated") return -(ageMinutes(item, now) ?? Number.MAX_SAFE_INTEGER);
  const n = num(item, field);
  if (n !== null) return n;
  return (str(item, field) ?? "￿").toLowerCase();
}

export function sortItems(items: LiveItem[], config: ViewConfig, now: number): LiveItem[] {
  const dir = config.sort.dir === "asc" ? 1 : -1;
  return [...items].sort((a, b) => {
    const av = ordinal(a, config.sort.field, now);
    const bv = ordinal(b, config.sort.field, now);
    let cmp: number;
    if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
    else cmp = String(av).localeCompare(String(bv));
    if (cmp !== 0) return cmp * dir;
    // Tie-break on recency so a stable list still reads newest-first.
    const aa = ageMinutes(a, now) ?? Number.MAX_SAFE_INTEGER;
    const ba = ageMinutes(b, now) ?? Number.MAX_SAFE_INTEGER;
    return aa - ba;
  });
}

// ── Grouping ─────────────────────────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = {
  decision: "Decisions",
  blocked: "Blocked",
  review: "Review",
  action: "Actions",
  concern: "Concerns",
  signal: "Signals",
};

/**
 * Columns come from the schema's options, not from the rows present — an empty
 * status column still renders, which is what makes a kanban a place to drop
 * work rather than a summary of work that already exists.
 */
export function groupItems(
  items: LiveItem[],
  config: ViewConfig,
  schema: FieldSchema[],
): ItemGroup[] {
  const name = config.groupBy;
  if (!name) return [{ key: "all", label: "All", items }];

  const field = fieldByName(schema, name);
  const buckets = new Map<string, LiveItem[]>();
  const order: string[] = [];
  const push = (key: string, item: LiveItem) => {
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(item);
  };

  if (field) {
    for (const opt of field.options) {
      buckets.set(opt.value, []);
      order.push(opt.value);
    }
  }

  for (const item of items) {
    const values = fieldValues(item, name);
    if (values.length === 0) push("-", item);
    else values.forEach(v => push(v, item));
  }

  const label = (key: string) => {
    if (key === "-") return `No ${humanize(name).toLowerCase()}`;
    if (name === "kind") return KIND_LABEL[key] ?? humanize(key);
    if (name === "owner") return key.startsWith("@") ? key : `@${key}`;
    return humanize(key);
  };

  const groups = order.map(key => ({ key, label: label(key), items: buckets.get(key) ?? [] }));

  // Status and priority carry a natural order; anything else falls back to size.
  if (name === "status") {
    groups.sort((a, b) => STATUS_ORDER.indexOf(a.key as never) - STATUS_ORDER.indexOf(b.key as never));
  } else if (name === "priority") {
    groups.sort((a, b) => PRIORITY_ORDER.indexOf(a.key as never) - PRIORITY_ORDER.indexOf(b.key as never));
  } else if (name === "kind") {
    const kinds = Object.keys(KIND_LABEL);
    groups.sort((a, b) => kinds.indexOf(a.key) - kinds.indexOf(b.key));
  }

  return config.mode === "board" ? groups : groups.filter(g => g.items.length > 0);
}

export function applyView(
  items: LiveItem[],
  config: ViewConfig,
  schema: FieldSchema[],
  now: number,
): ItemGroup[] {
  return groupItems(sortItems(filterItems(items, config), config, now), config, schema);
}

/** Counts for the lens tabs — computed off the unfiltered set so a tab shows
 *  what switching to it would reveal. */
export function lensCounts(items: LiveItem[]): Record<Lens | "all", number> {
  const counts: Record<Lens | "all", number> = {
    needs_you: 0,
    in_flight: 0,
    resolved: 0,
    all: items.length,
  };
  for (const item of items) counts[lensOf(item)] += 1;
  return counts;
}

/** What the row is waiting on, phrased for the cockpit's second line. */
export function waitingOn(item: LiveItem): string | null {
  const blockedBy = arr(item, "blocked_by");
  if (blockedBy.length) return `waiting on ${blockedBy.join(", ")}`;
  if (kindOf(item) === "decision" && statusOf(item) === "in_review") return "awaiting a call";
  return null;
}
