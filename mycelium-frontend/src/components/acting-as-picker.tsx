// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, Pencil, Plus, UserRound } from "lucide-react";
import {
  createUser,
  fetchTeams,
  fetchUsers,
  logFetchError,
  type Team,
  type User,
} from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { useAuthSession } from "@/components/auth-session";
import { Monogram } from "@/components/ui/monogram";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TagInput } from "@/components/ui/tag-input";
import { CopyField } from "@/components/ui/copy-field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const SLUG = /^[a-z0-9][a-z0-9._-]*$/;
const normHandle = (s: string) => s.trim().replace(/^@/, "").toLowerCase();

interface Form {
  handle: string;
  displayName: string;
  teams: string[];
  notify: string;
  isNew: boolean;
}

const BLANK: Form = { handle: "", displayName: "", teams: [], notify: "", isNew: true };

interface BoundUser {
  handle: string;
  display_name: string;
  teams: string[];
  notify: string | null;
}

/** The `mycelium iam` command that reproduces this user record and binds the
 *  machine's client to it — fully specified so it's deterministic on any machine
 *  and safe to re-run (the write is content-idempotent). */
function iamCommand(u: BoundUser): string {
  const arg = (v: string) => (/[\s"']/.test(v) ? `"${v.replace(/"/g, '\\"')}"` : v);
  const parts = [`mycelium iam ${u.handle}`];
  if (u.display_name) parts.push(`--name ${arg(u.display_name)}`);
  for (const t of u.teams) parts.push(`--team ${t}`);
  if (u.notify) parts.push(`--notify ${arg(u.notify)}`);
  return parts.join(" ");
}

/**
 * The identity surface: pick who the browser acts as (the self-asserted "me"
 * that scopes "my agents"/"my team" and stamps the chat sender), and manage the
 * user records inline — no CLI round-trip. Two views: a lightweight switcher and
 * a full editor (name, teams, notify). Saved locally via the current-user context.
 */
export function ActingAsPicker() {
  const { principal, setPrincipal } = useCurrentUser();
  const { signedIn, handle: sessionHandle, logout } = useAuthSession();
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [view, setView] = useState<"switch" | "edit" | "bound">("switch");
  const [form, setForm] = useState<Form>(BLANK);
  const [bound, setBound] = useState<BoundUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    fetchUsers().then(setUsers).catch((err) => {
      logFetchError("fetchUsers")(err);
      setUsers([]);
    });
    fetchTeams().then(setTeams).catch(logFetchError("fetchTeams"));
  }, []);

  useEffect(() => {
    if (open) {
      refresh();
      setView("switch");
      setError(null);
    }
  }, [open, refresh]);

  // Selecting or saving a user sets the browser identity AND reveals the CLI
  // command to bind a coding-agent machine to the same identity (progressive
  // disclosure — the command only shows once you've chosen who you are).
  const bindTo = (u: BoundUser) => {
    setPrincipal(u.handle);
    setBound(u);
    setView("bound");
  };

  const startNew = () => {
    setForm(BLANK);
    setError(null);
    setView("edit");
  };

  const startEdit = (u: User) => {
    setForm({
      handle: u.handle,
      displayName: u.display_name,
      teams: u.teams,
      notify: u.notify ?? "",
      isNew: false,
    });
    setError(null);
    setView("edit");
  };

  const save = async () => {
    const handle = normHandle(form.handle);
    if (!handle) {
      setError("Enter a handle.");
      return;
    }
    if (!SLUG.test(handle)) {
      setError("Handle must be lowercase letters, digits, . _ or -, with no spaces.");
      return;
    }
    try {
      const notify = form.notify.trim() || null;
      await createUser({ handle, display_name: form.displayName.trim(), teams: form.teams, notify });
      refresh();
      bindTo({ handle, display_name: form.displayName.trim(), teams: form.teams, notify });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  // A new handle that matches an existing user would upsert (overwrite) it —
  // offer to edit that record instead of silently clobbering it.
  const clash =
    form.isNew ? users.find((u) => u.handle === normHandle(form.handle)) : undefined;

  const teamSuggestions = teams.map((t) => t.team);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button variant="ghost" size="sm" />}
        title="Choose the user you're acting as"
      >
        {principal ? (
          <Monogram handle={principal} color="var(--muted-foreground)" className="size-5" />
        ) : (
          <UserRound className="size-3.5" />
        )}
        <span className="font-mono">{principal ? `@${principal}` : "acting as…"}</span>
      </DialogTrigger>

      <DialogContent className="sm:max-w-sm">
        {view === "switch" && (
          <>
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">Acting as</DialogTitle>
            </DialogHeader>

            {signedIn && (
              // Signed in through the hub's identity provider: the handle is the
              // token's, not a free choice — a gated hub attributes writes to the
              // token, so switching here would only earn a 403. Offer sign-out.
              <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-border bg-surface/40 px-3 py-2">
                <span className="min-w-0 text-label">
                  <span className="text-micro text-muted-foreground">Signed in as </span>
                  <span className="font-mono text-text">@{sessionHandle}</span>
                </span>
                <Button variant="ghost" size="xs" onClick={logout}>
                  Sign out
                </Button>
              </div>
            )}

            <div className="mt-2 max-h-64 overflow-y-auto border border-border">
              <button
                type="button"
                onClick={() => {
                  setPrincipal("");
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-label hover:bg-surface border-b border-border last:border-b-0"
              >
                <span className={principal === "" ? "text-accent" : "text-muted-foreground"}>
                  Anonymous
                </span>
              </button>

              {users.map((u) => (
                <div
                  key={u.handle}
                  className="group flex items-center gap-2.5 px-3 py-2 hover:bg-surface border-b border-border last:border-b-0"
                >
                  <button
                    type="button"
                    onClick={() => bindTo(u)}
                    className="flex min-w-0 flex-1 items-center gap-2.5 text-left text-label"
                  >
                    <Monogram handle={u.handle} color="var(--muted-foreground)" className="size-7" />
                    <span className="min-w-0">
                      <span
                        className={`block truncate font-mono ${principal === u.handle ? "text-accent" : "text-text"}`}
                      >
                        @{u.handle}
                      </span>
                      {(u.display_name || u.teams.length > 0) && (
                        <span className="block truncate text-micro text-muted-foreground">
                          {u.display_name}
                          {u.teams.length > 0
                            ? `${u.display_name ? " · " : ""}${u.teams.join(", ")}`
                            : ""}
                        </span>
                      )}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => startEdit(u)}
                    aria-label={`Edit @${u.handle}`}
                    className="flex-shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-text group-hover:opacity-100"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                </div>
              ))}

              {users.length === 0 && (
                <div className="px-3 py-2 text-micro text-muted-foreground">
                  No users yet.
                </div>
              )}
            </div>

            <Button variant="secondary" size="sm" onClick={startNew} className="mt-2 self-start">
              <Plus className="size-3.5" />
              New user
            </Button>
          </>
        )}

        {view === "edit" && (
          <>
            <DialogHeader>
              <button
                type="button"
                onClick={() => setView("switch")}
                className="mb-1 flex items-center gap-1 text-micro text-muted-foreground hover:text-text"
              >
                <ChevronLeft className="size-3.5" />
                Users
              </button>
              <DialogTitle className="text-ui font-semibold text-text">
                {form.isNew ? "New user" : `Edit @${form.handle}`}
              </DialogTitle>
            </DialogHeader>

            <div className="mt-2 space-y-3">
              <label className="block space-y-1">
                <span className="text-micro text-muted-foreground">Handle</span>
                <Input
                  placeholder="e.g. avery"
                  value={form.handle}
                  disabled={!form.isNew}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, handle: e.target.value }));
                    setError(null);
                  }}
                />
              </label>

              {clash && (
                <div className="text-micro text-muted-foreground">
                  <span className="font-mono text-text">@{clash.handle}</span> already exists.{" "}
                  <button
                    type="button"
                    onClick={() => startEdit(clash)}
                    className="text-accent hover:underline"
                  >
                    Edit it instead
                  </button>
                </div>
              )}

              <label className="block space-y-1">
                <span className="text-micro text-muted-foreground">Display name</span>
                <Input
                  placeholder="e.g. Avery Quinn"
                  value={form.displayName}
                  onChange={(e) => setForm((f) => ({ ...f, displayName: e.target.value }))}
                />
              </label>

              <div className="space-y-1">
                <span className="text-micro text-muted-foreground">Teams</span>
                <TagInput
                  value={form.teams}
                  onChange={(teams) => setForm((f) => ({ ...f, teams }))}
                  suggestions={teamSuggestions}
                  placeholder="type a team, Enter to add"
                  ariaLabel="Teams"
                />
              </div>

              <label className="block space-y-1">
                <span className="text-micro text-muted-foreground">
                  Notify <span className="text-faint">(where escalations reach you)</span>
                </span>
                <Input
                  placeholder="email or webhook (optional)"
                  value={form.notify}
                  onChange={(e) => setForm((f) => ({ ...f, notify: e.target.value }))}
                />
              </label>

              {error && (
                <div className="text-micro text-red leading-relaxed" role="alert">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="secondary" size="sm" onClick={() => setView("switch")}>
                  Cancel
                </Button>
                <Button size="sm" onClick={save} disabled={!form.handle.trim()}>
                  Save &amp; act as
                </Button>
              </div>
            </div>
          </>
        )}

        {view === "bound" && bound && (
          <>
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">
                Acting as @{bound.handle}
              </DialogTitle>
            </DialogHeader>

            <div className="mt-2 space-y-3">
              <p className="text-label text-muted-foreground leading-relaxed">
                Set in this browser. To attribute a coding agent&apos;s work to{" "}
                <span className="font-mono text-text">@{bound.handle}</span>, bind that
                machine&apos;s client to this identity. Run it there:
              </p>
              <CopyField value={iamCommand(bound)} />
              <p className="text-micro text-faint leading-relaxed">
                Sets the machine&apos;s identity and reproduces this user record. Safe to re-run.
              </p>
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="secondary" size="sm" onClick={() => setView("switch")}>
                  Switch user
                </Button>
                <Button size="sm" onClick={() => setOpen(false)}>
                  Done
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
