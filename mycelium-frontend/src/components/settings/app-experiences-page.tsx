// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { appCall, saveAndRestart, useApp, type AppState, type Experience, type HubSettings } from "@/lib/desktop-app";
import { ActionError, RestartSave, useAppAction } from "./app-save";
import { Note, Row, Section, SettingsPage } from "./settings-ui";

const count = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;

/** Ready-made rooms to explore, each added from a file the person was given.
 *  The hub reads what's added when it next starts. */
export function AppExperiencesPage() {
  const { data: state } = useApp<AppState>("get_state");
  return (
    <SettingsPage title="Experiences" scope="Example rooms you can try.">
      {state?.settings?.mode === "client" ? <HubExperiences /> : state ? <LocalExperiences state={state} /> : null}
    </SettingsPage>
  );
}

function LocalExperiences({ state }: { state: AppState }) {
  const { data: list, mutate, error: readError } = useApp<Experience[]>("get_experiences");
  const [changed, setChanged] = useState(false);
  const { busy, error, run } = useAppAction();
  const add = (id: string) =>
    void run(async () => {
      const now = await appCall<Experience[] | null>("add_experience", { id });
      if (!now) return; // they cancelled the picker
      await mutate(now, { revalidate: false });
      setChanged(true);
    });
  const remove = (id: string) =>
    void run(async () => {
      await mutate(await appCall<Experience[]>("remove_experience", { id }), { revalidate: false });
      setChanged(true);
    });
  if (readError) return <Note tone="error">{String(readError.message ?? readError)}</Note>;
  if (!list) return <Note>Looking…</Note>;
  return (
    <>
      <Section title="On this machine">
        {list.map((x) => (
          <Row
            key={x.id}
            label={x.title}
            help={x.added ? `${count(x.scenarios, x.unit)} · added from a file` : x.description}
          >
            {x.added && (
              <>
                <Link href={x.open} className="text-label text-accent hover:underline">
                  Open
                </Link>
                <Button variant="ghost" size="sm" onClick={() => remove(x.id)} disabled={busy}>
                  Remove
                </Button>
              </>
            )}
            <Button variant="outline" size="sm" onClick={() => add(x.id)} disabled={busy}>
              {x.added ? "Replace from a file…" : "Add from a file…"}
            </Button>
          </Row>
        ))}
      </Section>
      {changed && state.settings && (
        <div className="mt-4 flex items-center justify-end gap-3">
          <span className="text-micro text-muted-foreground">The hub reads it when it restarts.</span>
          <RestartSave busy={busy} onSave={() => void run(() => saveAndRestart(state.settings!))} />
        </div>
      )}
      <ActionError error={error} />
    </>
  );
}

function HubExperiences() {
  const { data: hub, error } = useApp<HubSettings>("get_hub_settings");
  if (error) return <Note tone="error">Couldn&apos;t ask your team&apos;s hub.</Note>;
  if (!hub) return <Note>Asking your team&apos;s hub…</Note>;
  return (
    <Section title="On your team's hub" note="Set on that hub.">
      {hub.experiences.length === 0 && <Row label="None yet." />}
      {hub.experiences.map((x) => (
        <Row key={x.id} label={x.title} help={`${count(x.scenarios, x.unit)} · on the hub`}>
          <Link href={x.open} className="text-label text-accent hover:underline">
            Open
          </Link>
        </Row>
      ))}
    </Section>
  );
}
