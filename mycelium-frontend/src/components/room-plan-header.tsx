// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchPlan,
  togglePlanTask,
  addPlanTask,
  setPlanTitle,
  type PlanResponse,
  type PlanFile,
} from "@/lib/api";
import { ListChecks } from "lucide-react";
import { MarkdownContent } from "./markdown-content";
import { EmptyState } from "@/components/empty-state";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  roomName: string;
  refreshTrigger: number;
}

// Filter the "title" file out of file chips; its content is the headline above.
const TITLE_SLUG = "title";

type Open =
  | { kind: "none" }
  | { kind: "tasks" }
  | { kind: "file"; slug: string };

export function RoomPlanHeader({ roomName, refreshTrigger }: Props) {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [open, setOpen] = useState<Open>({ kind: "tasks" });
  const [newTaskText, setNewTaskText] = useState("");

  const load = useCallback(async () => {
    try {
      setPlan(await fetchPlan(roomName));
    } catch {}
  }, [roomName]);

  // Reload on mount, on refreshTrigger bumps, and on a slow poll. A
  // negotiation consensus compiles plan/tasks.md on the backend; that write
  // lands on the parent room without a memory_changed event this page sees,
  // so polling guarantees the materialized plan surfaces after consensus.
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load, refreshTrigger]);

  const startEditTitle = () => {
    setTitleDraft(plan?.title ?? "");
    setEditingTitle(true);
  };

  const saveTitle = async () => {
    await setPlanTitle(roomName, titleDraft.trim());
    setEditingTitle(false);
    await load();
  };

  const onToggleTask = async (taskId: string, done: boolean) => {
    await togglePlanTask(roomName, taskId, done);
    await load();
  };

  const onAddTask = async () => {
    const text = newTaskText.trim();
    if (!text) return;
    setNewTaskText("");
    await addPlanTask(roomName, text);
    await load();
  };

  const toggleOpen = (next: Open) => {
    setOpen(cur => {
      if (cur.kind === next.kind && (cur.kind !== "file" || cur.slug === (next as any).slug)) {
        return { kind: "none" };
      }
      return next;
    });
  };

  const files = (plan?.files ?? []).filter(f => f.slug !== TITLE_SLUG);
  const openCount = plan?.open_count ?? 0;
  const titleText = plan?.title;

  return (
    <div className="border-b border-border bg-paper/50 flex-shrink-0">
      {/* Title hero: italic Cormorant, no label */}
      <div className="px-8 pt-7 pb-5 group relative">
        {editingTitle ? (
          <textarea
            autoFocus
            value={titleDraft}
            onChange={e => setTitleDraft(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                saveTitle();
              } else if (e.key === "Escape") {
                setEditingTitle(false);
              }
            }}
            placeholder="name this plan…"
            rows={2}
            className="w-full bg-transparent border-none outline-none resize-none leading-[1.05] text-text placeholder:text-muted-foreground"
            style={{
              fontFamily: "var(--font-serif, 'Cormorant Garamond', Georgia, serif)",
              fontStyle: "italic",
              fontWeight: 600,
              fontSize: "2.5rem",
            }}
          />
        ) : (
          <button
            onClick={startEditTitle}
            className="w-full text-left leading-[1.05] transition-colors hover:text-accent"
            style={{
              fontFamily: "var(--font-serif, 'Cormorant Garamond', Georgia, serif)",
              fontStyle: "italic",
              fontWeight: 600,
              fontSize: "2.5rem",
              color: titleText ? "var(--text)" : "var(--muted-foreground)",
            }}
            title="click to edit"
          >
            {titleText || "name this plan…"}
          </button>
        )}
      </div>

      {/* Chip row */}
      <div className="px-8 pb-4 flex flex-wrap items-center gap-2">
        <Chip
          variant="accent"
          active={open.kind === "tasks"}
          onClick={() => toggleOpen({ kind: "tasks" })}
        >
          tasks
          {openCount > 0 && (
            <span className="ml-2 text-text font-semibold tabular">{openCount} open</span>
          )}
        </Chip>
        {files.map(f => (
          <Chip
            key={f.slug}
            active={open.kind === "file" && open.slug === f.slug}
            onClick={() => toggleOpen({ kind: "file", slug: f.slug })}
          >
            {f.slug}.md
          </Chip>
        ))}
      </div>

      {/* Inline disclosure */}
      {open.kind === "tasks" && (
        <TasksDisclosure
          plan={plan}
          newTaskText={newTaskText}
          setNewTaskText={setNewTaskText}
          onAddTask={onAddTask}
          onToggleTask={onToggleTask}
        />
      )}
      {open.kind === "file" && (
        <FileDisclosure file={files.find(f => f.slug === open.slug)} />
      )}
    </div>
  );
}

function TasksDisclosure({
  plan,
  newTaskText,
  setNewTaskText,
  onAddTask,
  onToggleTask,
}: {
  plan: PlanResponse | null;
  newTaskText: string;
  setNewTaskText: (v: string) => void;
  onAddTask: () => void | Promise<void>;
  onToggleTask: (id: string, done: boolean) => void | Promise<void>;
}) {
  const tasks = plan?.tasks ?? [];
  return (
    <div className="border-t border-border bg-bg/60 max-h-[44vh] overflow-y-auto">
      <div className="px-8 py-4 flex gap-2 border-b border-border/60">
        <Input
          className="flex-1"
          placeholder="add a task…"
          value={newTaskText}
          onChange={e => setNewTaskText(e.target.value)}
          onKeyDown={e => e.key === "Enter" && onAddTask()}
        />
        <Button
          size="lg"
          onClick={() => onAddTask()}
          disabled={!newTaskText.trim()}
        >
          Add
        </Button>
      </div>
      {tasks.length === 0 ? (
        <EmptyState size="sm" icon={ListChecks} title="No tasks yet" description="Add one above, or reach consensus to compile a plan." />
      ) : (
        <ul>
          {tasks.map(t => (
            <li key={t.id}>
              <label className="flex items-start gap-3 px-8 py-2.5 border-b border-border/40 cursor-pointer hover:bg-hairline">
                <Checkbox
                  checked={t.done}
                  onCheckedChange={(checked) => onToggleTask(t.id, checked === true)}
                  className="mt-0.5"
                />
                <span className={"text-body flex-1 " + (t.done ? "line-through text-muted-foreground" : "text-text")}>
                  {t.text}
                </span>
                <span className="font-mono text-micro text-faint tabular flex-shrink-0">{t.slug}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FileDisclosure({ file }: { file: PlanFile | undefined }) {
  if (!file) return null;
  return (
    <div className="border-t border-border bg-bg/60 max-h-[44vh] overflow-y-auto px-8 py-5">
      <MarkdownContent>{file.content || "_(empty)_"}</MarkdownContent>
    </div>
  );
}
