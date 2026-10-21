// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { desktopMachine } from "@/lib/desktop";
import { saveAndRestart, useApp, withChange, type AppState, type HubSettings, type VoiceModel } from "@/lib/desktop-app";
import { ActionError, RestartSave, useAppAction } from "./app-save";
import { Note, Row, Section, Segmented, SettingsPage, Toggle } from "./settings-ui";

/** Talking into the message box: off unless chosen, and what each speech
 *  model costs, since turning it on downloads one. */
export function AppVoicePage() {
  const machine = desktopMachine();
  const { data: state } = useApp<AppState>("get_state");
  const saved = state?.settings ?? null;
  // What the person changed, over what's saved.
  const [draft, setDraft] = useState<{ voice: boolean; model: VoiceModel } | null>(null);
  const voice = draft?.voice ?? !!saved?.voice;
  const model = draft?.model ?? saved?.voiceModel ?? "fast";
  const setVoice = (next: boolean) => setDraft({ voice: next, model });
  const setModel = (next: VoiceModel) => setDraft({ voice, model: next });
  const { busy, error, run } = useAppAction();
  const changed = !!saved && (voice !== !!saved.voice || model !== (saved.voiceModel ?? "fast"));

  if (saved?.mode === "client") {
    return (
      <SettingsPage title="Voice" scope="Talking instead of typing.">
        <Note>Voice works with a hub on this {machine}. Connected to a team&apos;s hub, the app doesn&apos;t offer the mic.</Note>
      </SettingsPage>
    );
  }
  return (
    <SettingsPage
      title="Voice"
      scope={`Talking instead of typing. It runs on this ${machine}, in English, and your audio isn't saved or sent anywhere.`}
      actions={changed ? <RestartSave busy={busy} onSave={() => void run(() => saveAndRestart(withChange(saved!, { voice, voiceModel: model })))} /> : undefined}
    >
      <Section title="Voice">
        <Row
          id="voice.on"
          label="Talk instead of type"
          help="A mic in every message box: what you say is typed into it, and nothing sends until you do. ⌘⌥V turns it on and off."
        >
          <Toggle label="Talk instead of type" checked={voice} onChange={setVoice} />
        </Row>
        {voice && (
          <Row
            id="voice.model"
            label="Speech model"
            help={
              model === "fast"
                ? "A 150 MB download, and about 500 MB of memory while you talk."
                : "About half the mistakes. A 480 MB download, made the first time you turn on the mic, and about 1.4 GB of memory while you talk."
            }
          >
            <Segmented
              label="Speech model"
              value={model}
              onChange={setModel}
              options={[
                { value: "fast", label: "Fast" },
                { value: "accurate", label: "Accurate" },
              ]}
            />
          </Row>
        )}
      </Section>
      <ActionError error={error} />
    </SettingsPage>
  );
}

/** Anonymous usage stats: off unless ticked, and only for a hub on this machine. */
export function AppPrivacyPage() {
  const { data: state } = useApp<AppState>("get_state");
  const saved = state?.settings ?? null;
  const [draft, setShare] = useState<boolean | null>(null);
  const share = draft ?? !!saved?.shareUsage;
  const { busy, error, run } = useAppAction();
  const changed = !!saved && share !== !!saved.shareUsage;

  return (
    <SettingsPage
      title="Privacy"
      scope="Only counts of tasks, flows and agents. Never names, rooms or messages."
      actions={changed ? <RestartSave busy={busy} onSave={() => void run(() => saveAndRestart(withChange(saved!, { shareUsage: share })))} /> : undefined}
    >
      {saved?.mode === "client" ? (
        <HubPrivacy />
      ) : (
        <Section title="Usage stats">
          <Row id="privacy.share" label="Share anonymous usage stats" help="You can see them on the Metrics page.">
            <Toggle label="Share anonymous usage stats" checked={share} onChange={setShare} />
          </Row>
        </Section>
      )}
      <ActionError error={error} />
    </SettingsPage>
  );
}

function HubPrivacy() {
  const { data: hub, error } = useApp<HubSettings>("get_hub_settings");
  if (error) return <Note tone="error">Couldn&apos;t ask your team&apos;s hub.</Note>;
  if (!hub) return <Note>Asking your team&apos;s hub…</Note>;
  return (
    <Note>
      {hub.share_usage
        ? "Your team's hub shares anonymous usage stats: counts of tasks, flows and agents, never names, rooms or messages."
        : "Your team's hub doesn't share usage stats."}{" "}
      Set on that hub.
    </Note>
  );
}
