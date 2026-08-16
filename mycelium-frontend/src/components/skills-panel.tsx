// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { deleteSkill, fetchSkills, saveSkill, type Skill } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { DetailDrawer } from "@/components/detail-drawer";
import { EmptyState } from "@/components/empty-state";
import { MarkdownContent } from "@/components/markdown-content";
import { Skeleton } from "@/components/ui/skeleton";

// The frontend surface of the global skills store (#617). Skills are project-
// level (reusable across rooms), so this panel isn't scoped to a room — it lists
// every skill and lets you read, add, or remove one. The composer's `/` trigger
// (#619) sources its autocomplete from the same store.

const SLUG_RE = /^[a-z0-9][a-z0-9._-]*$/;

interface CreateFormProps {
  onCancel: () => void;
  onCreated: () => void;
  author: string;
}

function CreateForm({ onCancel, onCreated, author }: CreateFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = SLUG_RE.test(name) && body.trim().length > 0;

  const submit = async () => {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await saveSkill({ name, description, body, created_by: author });
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 p-3">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="skill-name (kebab-case)"
        className="rounded-lg border border-border bg-surface px-2.5 py-1.5 font-mono text-label text-text focus:border-accent focus:outline-none"
      />
      {name && !SLUG_RE.test(name) && (
        <span className="text-micro text-red">Use lowercase letters, digits, and . _ - only.</span>
      )}
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="One-line description"
        className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-label text-text focus:border-accent focus:outline-none"
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Skill body — the instructions / prose…"
        rows={6}
        className="resize-none rounded-lg border border-border bg-surface px-2.5 py-1.5 text-label text-text focus:border-accent focus:outline-none"
      />
      {error && <span className="text-micro text-red">{error}</span>}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={!valid || saving}
          className="rounded-lg bg-accent px-3 py-1.5 text-label font-medium text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Create skill"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-3 py-1.5 text-label text-muted-foreground transition-colors hover:text-text"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export function SkillsPanel() {
  const { principal } = useCurrentUser();
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    fetchSkills().then(setSkills).catch(() => setSkills([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onCreated = () => {
    setCreating(false);
    load();
  };

  const remove = async (name: string) => {
    await deleteSkill(name);
    setSelected(null);
    load();
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-label font-medium text-text">
          Skills{skills ? ` · ${skills.length}` : ""}
        </span>
        <button
          type="button"
          onClick={() => setCreating((c) => !c)}
          aria-label="Add skill"
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <Plus className="size-4" />
        </button>
      </div>

      {creating && (
        <div className="border-b border-border">
          <CreateForm author={principal.trim() || "user"} onCancel={() => setCreating(false)} onCreated={onCreated} />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {skills === null ? (
          <div className="flex flex-col gap-2 p-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-4/5" />
          </div>
        ) : skills.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            size="sm"
            title="No skills yet"
            description="Reusable prose you can drop into chat with /. Add one, or run 'mycelium skill set'."
          />
        ) : (
          <div className="p-1">
            {skills.map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() => setSelected(s)}
                className="flex w-full flex-col items-start gap-0.5 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-surface"
              >
                <span className="font-mono text-label text-accent">/{s.name}</span>
                {s.description && (
                  <span className="text-micro text-muted-foreground line-clamp-1">{s.description}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? `/${selected.name}` : ""}
        subtitle={selected ? `v${selected.version} · ${selected.created_by}` : undefined}
        actions={
          selected && (
            <button
              type="button"
              onClick={() => remove(selected.name)}
              aria-label="Delete skill"
              className="flex size-7 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-red"
            >
              <Trash2 className="size-4" />
            </button>
          )
        }
      >
        {selected && (
          <div className="flex flex-col gap-3 p-5">
            {selected.description && (
              <p className="text-label text-muted-foreground">{selected.description}</p>
            )}
            <div className="text-body text-text">
              <MarkdownContent>{selected.body}</MarkdownContent>
            </div>
          </div>
        )}
      </DetailDrawer>
    </div>
  );
}
