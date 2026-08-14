// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import { UserRound } from "lucide-react";
import { createUser, fetchUsers, logFetchError, type User } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { Monogram } from "@/components/ui/monogram";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

/**
 * Pick the principal the browser acts as — the self-asserted "me" that scopes
 * "my agents" / "my team". Lists the global user store; a new handle can be
 * registered inline. Persisted locally via the current-user context.
 */
export function ActingAsPicker() {
  const { principal, setPrincipal } = useCurrentUser();
  const [users, setUsers] = useState<User[]>([]);
  const [open, setOpen] = useState(false);
  const [newHandle, setNewHandle] = useState("");
  const [newName, setNewName] = useState("");

  const refresh = useCallback(() => {
    fetchUsers().then(setUsers).catch((err) => {
      logFetchError("fetchUsers")(err);
      setUsers([]);
    });
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  const register = async () => {
    const handle = newHandle.trim().replace(/^@/, "").toLowerCase();
    if (!handle) return;
    const created = await createUser({ handle, display_name: newName.trim() });
    if (created) {
      setPrincipal(created.handle);
      setNewHandle("");
      setNewName("");
      setOpen(false);
    }
  };

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
        <DialogHeader>
          <DialogTitle className="text-ui font-semibold text-text">Acting as</DialogTitle>
          <DialogDescription className="text-label text-muted-foreground leading-relaxed">
            Sets the handle your messages post under, and lets the agents list
            filter to the ones you own. Saved in this browser; there&apos;s no login yet.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-2 space-y-4">
          <div className="max-h-56 overflow-y-auto border border-border">
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
              <button
                type="button"
                key={u.handle}
                onClick={() => {
                  setPrincipal(u.handle);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-label hover:bg-surface border-b border-border last:border-b-0"
              >
                <Monogram handle={u.handle} color="var(--muted-foreground)" className="size-7" />
                <span
                  className={`font-mono ${principal === u.handle ? "text-accent" : "text-text"}`}
                >
                  @{u.handle}
                </span>
                {u.display_name && (
                  <span className="text-micro text-muted-foreground truncate">
                    {u.display_name}
                  </span>
                )}
                {u.teams.length > 0 && (
                  <span className="ml-auto text-micro text-muted-foreground">
                    {u.teams.join(", ")}
                  </span>
                )}
              </button>
            ))}
            {users.length === 0 && (
              <div className="px-3 py-2 text-micro text-muted-foreground">
                No users registered yet.
              </div>
            )}
          </div>

          <section className="space-y-2">
            <div className="text-label font-semibold text-text">Register a new user</div>
            <Input
              placeholder="handle (e.g. julia)"
              value={newHandle}
              onChange={(e) => setNewHandle(e.target.value)}
            />
            <Input
              placeholder="display name (optional)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <DialogClose render={<Button variant="secondary" size="sm" />}>Cancel</DialogClose>
              <Button size="sm" onClick={register} disabled={!newHandle.trim()}>
                Register &amp; act as
              </Button>
            </div>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
