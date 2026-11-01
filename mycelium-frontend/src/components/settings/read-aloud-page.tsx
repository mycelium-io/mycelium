// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { useNotifications, useReadAloud } from "@/components/notifications-provider";
import { fetchSpeechVoices } from "@/lib/api";
import { settingHref } from "@/lib/client-settings";
import { useIsDesktop } from "@/lib/desktop";
import {
  DEFAULT_SETTINGS,
  roomLevel,
  type NotificationSettings,
  type ReadAloudLength,
  type ReadAloudReads,
} from "@/lib/notifications";
import type { SkipRule } from "@/lib/on-screen";
import { useRooms } from "@/lib/room-data";
import { CheckChips, Note, Row, Section, Segmented, SettingsPage, Toggle } from "./settings-ui";

const READS: { value: ReadAloudReads; label: string }[] = [
  { value: "mentions", label: "Mentions of me" },
  { value: "rooms", label: "Everything in rooms I pick" },
];

const SKIPS: { value: SkipRule; label: string }[] = [
  { value: "thread", label: "The thread I have open" },
  { value: "room", label: "The room I have open" },
  { value: "never", label: "Nothing" },
];

const LENGTHS: { value: ReadAloudLength; label: string }[] = [
  { value: "start", label: "The start" },
  { value: "all", label: "All of it" },
];

const SPEEDS = [0.75, 1, 1.25, 1.5] as const;

/** How fast, as people say it. */
function speedLabel(speed: number): string {
  return speed === 1 ? "Normal" : `${speed}×`;
}

/**
 * Reading aloud, set by each person for themselves: whether it's on, what it
 * reads, what counts as already in front of them, how much of a message, and
 * the voice. Apart from the bell's settings, which no longer decide it; Do not
 * disturb still keeps it quiet.
 */
export function ReadAloudPage() {
  const { settings, setSettings } = useNotifications();
  const readAloud = useReadAloud();
  const desktop = useIsDesktop();
  const { rooms } = useRooms();
  const { data: voices } = useSWR(readAloud.available ? "speech-voices" : null, fetchSpeechVoices, {
    revalidateOnFocus: false,
  });
  const set = (patch: Partial<NotificationSettings>) => setSettings({ ...settings, ...patch });
  const reset = <K extends keyof NotificationSettings>(key: K) => () => set({ [key]: DEFAULT_SETTINGS[key] });
  const roomNames = rooms
    .map((r) => r.name)
    .filter((name) => roomLevel(settings, name) !== "muted")
    .sort();
  const hubVoice = voices?.default || "the speech server's own";
  const voiceOptions = [...new Set([...(voices?.voices ?? []), ...(settings.readAloudVoice ? [settings.readAloudVoice] : [])])];

  return (
    <SettingsPage
      title="Read aloud"
      scope={desktop ? "Saved in this app on this computer. Never sent to the hub." : "Saved in this browser. Never sent to the hub."}
    >
      {!readAloud.available ? (
        <Note>
          This hub has no speech server, so nothing can be read aloud. Whoever runs the hub sets one on the{" "}
          <Link href={settingHref("hub", "hub.speech")} className="text-accent hover:underline">
            Hub
          </Link>{" "}
          page.
        </Note>
      ) : (
        <>
          <Section
            title="Reading aloud"
            note="Each message is said with who sent it and where, and a popover on the bell shows the words as they're said. Nothing is read while a mic is open, while Mycelium is hidden, or while Do not disturb is on."
          >
            <Row
              id="read-aloud.on"
              label="Read aloud"
              changed={settings.readAloud !== DEFAULT_SETTINGS.readAloud}
              onReset={reset("readAloud")}
              defaultLabel="off"
            >
              <Button size="sm" variant="outline" onClick={readAloud.tryIt} disabled={readAloud.state.item !== null}>
                Try it
              </Button>
              <Toggle label="Read aloud" checked={settings.readAloud} onChange={(on) => set({ readAloud: on })} />
            </Row>
          </Section>

          <Section title="What it reads">
            <Row
              id="read-aloud.reads"
              label="Read"
              help={
                settings.readAloudReads === "rooms"
                  ? "Everything said in the rooms below, and mentions of you anywhere."
                  : "Messages that mention you or are sent to you: what rings the bell."
              }
              changed={settings.readAloudReads !== DEFAULT_SETTINGS.readAloudReads}
              onReset={reset("readAloudReads")}
              defaultLabel="mentions of me"
              below={
                settings.readAloudReads === "rooms" ? (
                  roomNames.length === 0 ? (
                    <Note>No rooms to pick yet.</Note>
                  ) : (
                    <CheckChips
                      label="Rooms read in full"
                      value={settings.readAloudRooms}
                      options={roomNames.map((name) => ({ value: name, label: name }))}
                      onChange={(next) => set({ readAloudRooms: next })}
                    />
                  )
                ) : null
              }
            >
              <Segmented label="Read" value={settings.readAloudReads} options={READS} onChange={(v) => set({ readAloudReads: v })} />
            </Row>
            <Row
              id="read-aloud.skip"
              label="Skip what's in front of me"
              help="A message already on your screen isn't read. Choose what counts: the thread it was said in is open, its room is open, or never skip."
              changed={settings.readAloudSkip !== DEFAULT_SETTINGS.readAloudSkip}
              onReset={reset("readAloudSkip")}
              defaultLabel="the thread I have open"
            >
              <Segmented
                label="Skip what's in front of me"
                value={settings.readAloudSkip}
                options={SKIPS}
                onChange={(v) => set({ readAloudSkip: v })}
              />
            </Row>
            <Row
              id="read-aloud.length"
              label="How much"
              help={
                settings.readAloudLength === "start"
                  ? "The first paragraph, or about twenty seconds. Read all on the popover says the rest."
                  : "The whole message, however long."
              }
              changed={settings.readAloudLength !== DEFAULT_SETTINGS.readAloudLength}
              onReset={reset("readAloudLength")}
              defaultLabel="the start"
            >
              <Segmented
                label="How much"
                value={settings.readAloudLength}
                options={LENGTHS}
                onChange={(v) => set({ readAloudLength: v })}
              />
            </Row>
          </Section>

          <Section title="Voice">
            <Row
              id="read-aloud.voice"
              label="Voice"
              help={`From the hub's speech server. Unset, it's the hub's voice (${hubVoice}).`}
              changed={settings.readAloudVoice !== DEFAULT_SETTINGS.readAloudVoice}
              onReset={reset("readAloudVoice")}
              defaultLabel="the hub's voice"
            >
              {voiceOptions.length > 0 ? (
                <select
                  aria-label="Voice"
                  value={settings.readAloudVoice ?? ""}
                  onChange={(e) => set({ readAloudVoice: e.target.value || null })}
                  className="h-7 max-w-48 rounded-md border border-border bg-transparent px-2 text-label text-text"
                >
                  <option value="">The hub&apos;s voice</option>
                  {voiceOptions.map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  aria-label="Voice"
                  placeholder="The hub's voice"
                  defaultValue={settings.readAloudVoice ?? ""}
                  onBlur={(e) => set({ readAloudVoice: e.target.value.trim() || null })}
                  className="h-7 w-40 rounded-md border border-border bg-transparent px-2 text-label text-text"
                />
              )}
            </Row>
            <Row
              id="read-aloud.speed"
              label="Speed"
              changed={settings.readAloudSpeed !== DEFAULT_SETTINGS.readAloudSpeed}
              onReset={reset("readAloudSpeed")}
              defaultLabel="normal"
            >
              <Segmented
                label="Speed"
                value={String(settings.readAloudSpeed)}
                options={SPEEDS.map((s) => ({ value: String(s), label: speedLabel(s) }))}
                onChange={(v) => set({ readAloudSpeed: Number(v) })}
              />
            </Row>
          </Section>
        </>
      )}
    </SettingsPage>
  );
}
