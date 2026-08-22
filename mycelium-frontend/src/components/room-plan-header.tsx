// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { togglePlanTask, addPlanTask, setPlanTitle, type PlanFile, type PlanResponse } from "@/lib/api";
import { useRoomPlan } from "@/lib/room-data";
import { ListChecks, AlertCircle } from "lucide-react";
import { MarkdownContent } from "./markdown-content";
import { EmptyState } from "@/components/empty-state";
import { Checkbox } from "@/components/ui/checkbox";
import { Chip } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";

interface Props {
  roomName: string;
}

// Filter the "title" file out of file chips; its content is the headline above.
const TITLE_SLUG = "title";

type Open =
  | { kind: "none" }
  | { kind: "tasks" }
  | { kind: "file"; slug: string };

export function RoomPlanHeader({ roomName }: Props) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [open, setOpen] = useState<Open>({ kind: "tasks" });
  const [newTaskText, setNewTaskText] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  // A negotiation consensus compiles plan/tasks.md on the backend, and that
  // write lands without a memory_changed event this page sees — so the plan is
  // the one room resource still worth polling closely, and `refresh` is what an
  // edit made here calls to see its own result.
  const { plan, refresh: load } = useRoomPlan(roomName);

  const startEditTitle = () => {
    setTitleDraft(plan?.title ?? "");
    setEditingTitle(true);
  };

  const saveTitle = async () => {
    setActionError(null);
    try {
      await setPlanTitle(roomName, titleDraft.trim());
      setEditingTitle(false);
      await load();
    } catch (err) {
      // Keep the editor open so the draft (and the retry) isn't lost.
      setActionError(err instanceof Error ? err.message : "Failed to save title");
    }
  };

  const onToggleTask = async (taskId: string, done: boolean) => {
    setActionError(null);
    try {
      await togglePlanTask(roomName, taskId, done);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to update task");
    }
  };

  const onAddTask = async () => {
    const text = newTaskText.trim();
    if (!text) return;
    setActionError(null);
    setNewTaskText("");
    try {
      await addPlanTask(roomName, text);
      await load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to add task");
      setNewTaskText(text); // restore the draft so the user doesn't retype it
    }
  };

  const toggleOpen = (next: Open) => {
    setOpen(cur => {
      const sameTarget =
        cur.kind === next.kind &&
        (cur.kind !== "file" || next.kind !== "file" || cur.slug === next.slug);
      return sameTarget ? { kind: "none" } : next;
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
          <Tooltip content="Click to rename the plan" side="bottom" align="start">
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
            >
              {titleText || "name this plan…"}
            </button>
          </Tooltip>
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

      {actionError && (
        <p role="alert" className="mx-8 mb-3 flex items-center gap-1.5 text-micro text-red">
          <AlertCircle className="size-3.5 flex-shrink-0" />
          {actionError}
        </p>
      )}

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
