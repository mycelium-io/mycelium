// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Add a machine to the Machines page, one of two ways:
 *
 * - **Pair** a remote machine: `mycelium runner pair` there prints a
 *   code, and entering it here pairs this browser's device key with it, so
 *   requests from this browser start there without approval (`device-key.ts`).
 * - **Add** a machine you use, by the id `mycelium runner` prints: it is
 *   listed here, and asks you there before it starts anything.
 */

import { useEffect, useState } from "react";
import { Check, KeyRound, Laptop, Loader2 } from "lucide-react";
import { pairRunner } from "@/lib/api";
import { fingerprint, normalizeCode, pairRequest, useDeviceKeyId } from "@/lib/device-key";
import { addMachine } from "@/lib/my-machines";
import { useIsDesktop } from "@/lib/desktop";
import { jobSettled, useRunnerJob, useRunnersRevalidate } from "@/lib/runners";
import { Button } from "@/components/ui/button";
import { CopyField } from "@/components/ui/copy-field";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { AddMachineCode, CONNECT_COMMAND } from "@/components/runner-fields";
import { cn } from "@/lib/utils";

export const PAIR_COMMAND = "mycelium runner pair";

type Way = "pair" | "add";

export function AddMachineDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [way, setWay] = useState<Way>("pair");
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogTitle>Add a machine</DialogTitle>
        <DialogDescription>
          Agents you start from here run on this machine. Each request needs approval on the machine, unless this
          computer is paired with it.
        </DialogDescription>
        <div role="tablist" aria-label="How to add it" className="flex gap-1 rounded-lg bg-hairline p-0.5">
          <WayTab active={way === "pair"} onClick={() => setWay("pair")} icon={<KeyRound className="size-3.5" />}>
            Pair a remote machine
          </WayTab>
          <WayTab active={way === "add"} onClick={() => setWay("add")} icon={<Laptop className="size-3.5" />}>
            Add a machine
          </WayTab>
        </div>
        {way === "pair" ? <PairForm onClose={onClose} /> : <AddForm />}
      </DialogContent>
    </Dialog>
  );
}

function WayTab({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex h-7 flex-1 items-center justify-center gap-1.5 rounded-md px-2 text-micro transition-colors",
        active ? "bg-bg font-medium text-text shadow-sm" : "text-muted-foreground hover:text-text",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function AddForm() {
  return (
    <div className="space-y-2 text-label text-muted-foreground">
      <p>Run this on the machine, with herdr open. Each request will need your approval there.</p>
      <CopyField value={CONNECT_COMMAND} className="font-mono" />
      <AddMachineCode />
    </div>
  );
}

function PairForm({ onClose }: { onClose: () => void }) {
  const desktop = useIsDesktop();
  const keyId = useDeviceKeyId();
  const revalidate = useRunnersRevalidate();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ runner: string; job: string } | null>(null);
  const { job } = useRunnerJob(pending?.runner ?? null, pending?.job ?? null);

  const clean = normalizeCode(code);
  const deviceName = name.trim() || (desktop ? "Mycelium for Mac" : "");
  const done = job?.status === "done";
  const result = (done ? job?.result : null) as { label?: string; name?: string; key?: string } | null;

  useEffect(() => {
    if (!done || !pending) return;
    addMachine(pending.runner);
    revalidate();
  }, [done, pending, revalidate]);

  const pair = async () => {
    if (!clean || !deviceName || busy) return;
    setBusy(true);
    setError(null);
    setPending(null);
    try {
      const { body } = await pairRequest(clean, deviceName);
      const queued = await pairRunner(body);
      setPending({ runner: queued.runner, job: queued.id });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't pair with it");
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div className="space-y-3">
        <p className="flex items-center gap-2 text-label text-text">
          <Check className="size-4 text-green" />
          Paired with {result.label ?? "the machine"} as &ldquo;{result.name}&rdquo;.
        </p>
        <p className="text-micro leading-relaxed text-muted-foreground">
          Check that the machine printed the same key:{" "}
          <span className="font-mono text-text">{fingerprint(result.key ?? "")}</span>. Requests from this computer
          now start without approval, within the pairing&apos;s limits.
        </p>
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    );
  }

  const waiting = pending !== null && !jobSettled(job);
  const failed = job?.status === "failed" ? (job.error ?? "The machine didn't pair.") : null;

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        void pair();
      }}
    >
      <div className="space-y-1.5 text-label text-muted-foreground">
        <p>Run this on the remote machine (its runner must be running). It prints a one-time code that expires in 10 minutes.</p>
        <CopyField value={PAIR_COMMAND} className="font-mono" />
        <p className="text-micro text-faint">
          Add <code className="font-mono">--folder</code>, <code className="font-mono">--cli</code>,{" "}
          <code className="font-mono">--swarms</code> or <code className="font-mono">--days</code> there to limit what
          this computer can start.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="space-y-1">
          <span className="block text-micro font-medium text-muted-foreground">Code</span>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="K7QM-4XHD-9RWA"
            spellCheck={false}
            autoComplete="off"
            autoFocus
            className="h-8 w-full rounded-md border border-border bg-bg px-2 font-mono text-label uppercase text-text placeholder:normal-case placeholder:text-faint focus:border-accent focus:outline-none"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-micro font-medium text-muted-foreground">This computer&apos;s name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={desktop ? "Mycelium for Mac" : "work laptop"}
            maxLength={40}
            autoComplete="off"
            className="h-8 w-full rounded-md border border-border bg-bg px-2 text-label text-text placeholder:text-faint focus:border-accent focus:outline-none"
          />
        </label>
      </div>
      <p className="text-micro leading-relaxed text-faint">
        {keyId ? (
          <>
            This computer&apos;s key: <span className="font-mono text-muted-foreground">{fingerprint(keyId)}</span>.
          </>
        ) : (
          "A key is created for this computer when you pair."
        )}{" "}
        The private key stays in this browser and can&apos;t be exported; the machine stores only the public key.
      </p>
      {(error || failed) && (
        <p role="alert" className="text-micro text-red">
          {error ?? failed}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        {(busy || waiting) && (
          <span className="flex items-center gap-1.5 text-micro text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {busy ? "Checking the code…" : "Waiting for the machine…"}
          </span>
        )}
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={!clean || !deviceName || busy || waiting}>
          Pair
        </Button>
      </div>
    </form>
  );
}
