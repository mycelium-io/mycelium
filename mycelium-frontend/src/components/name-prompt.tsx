// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { createUser } from "@/lib/api";
import { handleFromName, useRefreshUsers, useUsers } from "@/lib/people";
import { useCurrentUser } from "@/components/current-user";
import { useAuthSession } from "@/components/auth-session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Monogram } from "@/components/ui/monogram";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

// A handle is an identity and can be minted by a real IdP, so it allows the `@`
// a corporate SSO `preferred_username` carries. Keep in sync with the backend
// (`app/schemas.py`) and CLI (`protocol.py`) copies.
const HANDLE = /^[a-z0-9][a-z0-9._@-]*$/;

/** Set once someone answers or says "Not now", so a load never asks twice. */
const ASKED_KEY = "mycelium.name-asked";

function asked(): boolean {
  try {
    return window.localStorage.getItem(ASKED_KEY) === "1";
  } catch {
    return false;
  }
}

function markAsked(): void {
  try {
    window.localStorage.setItem(ASKED_KEY, "1");
  } catch {
    // Remembering is a convenience; at worst the question comes back next load.
  }
}

/**
 * Who are you? Asked once, on the first load of a browser that hasn't said.
 *
 * The answer is a name, the way a person thinks of themselves, and a handle
 * made from it (editable) that the rest of the system addresses them by. It
 * becomes the hub's user record, so messages from this browser show the name,
 * in the app and in the CLI. Someone already on the hub picks themselves
 * instead. Not asked when signed in, since the sign-in says who you are, and
 * changed later from the account menu.
 */
export function NamePrompt() {
  const { principal, setPrincipal, ready } = useCurrentUser();
  const { loading: authLoading, signedIn } = useAuthSession();
  const { users } = useUsers();
  const refreshUsers = useRefreshUsers();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [handle, setHandle] = useState("");
  const [handleEdited, setHandleEdited] = useState(false);
  const [editingHandle, setEditingHandle] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!ready || authLoading) return;
    // Asked only of a browser that hasn't said, and hasn't been asked.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(!principal && !signedIn && !asked());
  }, [ready, authLoading, principal, signedIn]);

  const derived = handleFromName(name);
  const chosen = (handleEdited ? handle : derived).trim().replace(/^@/, "").toLowerCase();
  const taken = users.find(u => u.handle.toLowerCase() === chosen);

  const close = () => {
    markAsked();
    setOpen(false);
  };

  const pick = (h: string) => {
    setPrincipal(h);
    close();
  };

  const save = async () => {
    if (!name.trim() || !chosen) return;
    if (!HANDLE.test(chosen)) {
      setError("A handle is lowercase letters, digits, and . _ - or @, with no spaces.");
      return;
    }
    if (taken) {
      setError(`Someone here is already @${chosen}. If that's you, pick yourself below; if not, change your handle.`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createUser({ handle: chosen, display_name: name.trim() });
      refreshUsers();
      pick(chosen);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that. Try again.");
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={o => (o ? setOpen(true) : close())}>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle className="text-ui font-semibold text-text">What should we call you?</DialogTitle>
          <DialogDescription className="text-label leading-relaxed text-muted-foreground">
            Your name goes on what you post here, and agents see it when you talk to them.
          </DialogDescription>
        </DialogHeader>

        <form
          className="mt-1 space-y-3"
          onSubmit={e => {
            e.preventDefault();
            void save();
          }}
        >
          <label className="block">
            <span className="mb-1 block text-micro text-muted-foreground">Your name</span>
            <Input
              id="your-name"
              autoFocus
              value={name}
              placeholder="e.g. Avery Quinn"
              onChange={e => {
                setName(e.target.value);
                setError(null);
              }}
            />
          </label>

          <div className="text-micro text-muted-foreground">
            {editingHandle ? (
              <label className="block">
                <span className="mb-1 block">Your handle</span>
                <Input
                  id="your-handle"
                  value={handleEdited ? handle : derived}
                  placeholder="e.g. avery"
                  onChange={e => {
                    setHandle(e.target.value);
                    setHandleEdited(true);
                    setError(null);
                  }}
                />
              </label>
            ) : (
              <span>
                {chosen ? (
                  <>
                    You&apos;ll be <span className="font-mono text-text">@{chosen}</span>.{" "}
                  </>
                ) : (
                  "Your handle is made from your name. "
                )}
                <button type="button" onClick={() => setEditingHandle(true)} className="text-accent hover:underline">
                  Change it
                </button>
              </span>
            )}
          </div>

          {error && (
            <p role="alert" className="text-micro leading-relaxed text-red">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" size="sm" onClick={close}>
              Not now
            </Button>
            <Button type="submit" size="sm" disabled={!name.trim() || !chosen || saving}>
              Continue
            </Button>
          </div>
        </form>

        {users.length > 0 && (
          <div className="mt-2 border-t border-border pt-3">
            <div className="mb-1.5 text-micro text-muted-foreground">Already here? Pick yourself</div>
            <ul className="max-h-40 overflow-y-auto">
              {users.map(u => (
                <li key={u.handle}>
                  <button
                    type="button"
                    onClick={() => pick(u.handle)}
                    className="flex w-full items-center gap-2.5 rounded px-1.5 py-1.5 text-left text-label hover:bg-hairline"
                  >
                    <Monogram handle={u.handle} color="var(--avatar-neutral)" className="size-6" />
                    <span className="min-w-0 flex-1 truncate text-text">{u.display_name || `@${u.handle}`}</span>
                    {u.display_name && <span className="font-mono text-micro text-faint">@{u.handle}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
