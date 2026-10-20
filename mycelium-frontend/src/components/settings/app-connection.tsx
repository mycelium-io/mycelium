// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { desktopMachine } from "@/lib/desktop";
import { appCall, saveAndRestart, useApp, withChange, type AppState, type Mode } from "@/lib/desktop-app";
import { ActionError, useAppAction } from "./app-save";
import { Row, Section, Segmented, Toggle } from "./settings-ui";

/** Where this machine's rooms live (here, or on a team's hub), and start at
 *  login: the app's own part of Hub and Connection. */
export function AppConnection() {
  const machine = desktopMachine();
  const { data: state } = useApp<AppState>("get_state");
  const saved = state?.settings ?? null;
  // What the person changed, over what's saved.
  const [draft, setDraft] = useState<{ mode: Mode; hubUrl: string } | null>(null);
  const mode = draft?.mode ?? saved?.mode ?? "hub";
  const hubUrl = draft?.hubUrl ?? saved?.hubUrl ?? "";
  const setMode = (next: Mode) => setDraft({ mode: next, hubUrl });
  const setHubUrl = (next: string) => setDraft({ mode, hubUrl: next });
  const { busy, error, run } = useAppAction();
  const changed = !!saved && (mode !== saved.mode || (mode === "client" && hubUrl.trim() !== (saved.hubUrl ?? "")));
  const save = () => {
    if (!saved) return;
    if (mode === "client" && !hubUrl.trim()) return;
    void run(() => saveAndRestart(withChange(saved, { mode, hubUrl })));
  };

  return (
    <>
      <Section title={`This ${machine}`}>
        <Row
          id="connection.where"
          label="Where your rooms live"
          help={
            mode === "hub"
              ? `On this ${machine}: everything stays here.`
              : "On your team's hub: you join rooms someone else hosts, and this machine's runner starts agents here for it."
          }
        >
          <Segmented
            label="Where your rooms live"
            value={mode}
            onChange={setMode}
            options={[
              { value: "hub", label: `On this ${machine}` },
              { value: "client", label: "On my team's hub" },
            ]}
          />
        </Row>
        {mode === "client" && (
          <Row id="connection.hub-url" label="The hub's address" help="For example https://hub.example.com.">
            <input
              value={hubUrl}
              onChange={(e) => setHubUrl(e.target.value)}
              placeholder="https://hub.example.com"
              spellCheck={false}
              autoCapitalize="none"
              aria-label="The hub's address"
              className="w-72 rounded-md border border-border bg-bg px-2.5 py-1 font-mono text-micro text-text outline-none focus:border-accent"
            />
          </Row>
        )}
        {changed && (
          <Row
            label="Switch"
            help={`Mycelium asks on this ${machine} first, then restarts. Agents running here keep running.`}
            below={<ActionError error={error} />}
          >
            <Button size="sm" onClick={save} disabled={busy || (mode === "client" && !hubUrl.trim())}>
              {busy ? "Switching…" : "Switch"}
            </Button>
          </Row>
        )}
        <StartAtLogin />
      </Section>
    </>
  );
}

function StartAtLogin() {
  const { data: on, mutate } = useApp<boolean>("get_autostart");
  return (
    <Row id="connection.autostart" label="Start Mycelium when I log in" help="Changes right away.">
      <Toggle
        label="Start Mycelium when I log in"
        checked={!!on}
        onChange={(next) => void mutate(appCall<boolean>("set_autostart", { on: next }), { optimisticData: next })}
      />
    </Row>
  );
}
