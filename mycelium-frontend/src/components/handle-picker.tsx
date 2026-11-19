// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { pickHandle } from "@/lib/api";
import { useAuthSession } from "@/components/auth-session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/**
 * Pick your handle: asked once, of a signed-in person whose sign-in gives no
 * handle the hub can use (the short one from their email is taken, or isn't a
 * valid handle). The hub keeps the answer with their sign-in, so it isn't asked
 * again, and refuses anything else until it's answered.
 */
export function HandlePicker() {
  const { signedIn, needsHandle, suggested, refresh } = useAuthSession();
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const open = signedIn && needsHandle;

  const save = async () => {
    const wanted = handle.trim().replace(/^@/, "").toLowerCase();
    if (!wanted) return;
    setSaving(true);
    setError(null);
    try {
      await pickHandle(wanted);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open}>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle className="text-ui font-semibold text-text">Pick your handle</DialogTitle>
          <DialogDescription className="text-label leading-relaxed text-muted-foreground">
            {suggested
              ? `@${suggested} is taken here. Your handle is how people and agents mention you.`
              : "Your sign-in doesn't give a handle this hub can use. Your handle is how people and agents mention you."}
          </DialogDescription>
        </DialogHeader>
        <form
          className="mt-1 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label className="block">
            <span className="mb-1 block text-micro text-muted-foreground">Your handle</span>
            <Input
              id="your-handle"
              autoFocus
              value={handle}
              placeholder={suggested ? `e.g. ${suggested}2` : "e.g. avery"}
              onChange={(e) => {
                setHandle(e.target.value);
                setError(null);
              }}
            />
          </label>
          {error && (
            <p role="alert" className="text-micro leading-relaxed text-red">
              {error}
            </p>
          )}
          <div className="flex justify-end pt-1">
            <Button type="submit" size="sm" disabled={!handle.trim() || saving}>
              Continue
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
