// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useTheme } from "next-themes";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { KbdChord } from "@/components/ui/kbd";
import { COMMON_ZONES, localZone } from "@/lib/board/activity";
import {
  exportClientSettings,
  importClientSettings,
  resetClientSetting,
  setClientSetting,
  useClientSetting,
  type AgentAvatars,
  type SendKey,
} from "@/lib/client-settings";
import { Monogram } from "@/components/ui/monogram";
import { Select } from "@/components/ui/select";
import { useIsClient } from "@/lib/client-hooks";
import { useIsDesktop } from "@/lib/desktop";
import { SYSTEM, THEMES } from "@/lib/themes";
import { CUSTOM_THEME } from "@/lib/custom-themes";
import { useCustomThemes } from "@/components/custom-theme";
import { CustomThemesRow } from "./custom-themes-row";
import { Note, Row, Section, Segmented, SettingsPage } from "./settings-ui";

/** How an imported theme is told apart from a built-in one in the dropdown. */
const CUSTOM_PREFIX = "custom:";

/** Download what this browser has set, to take to another one. */
function exportFile() {
  const blob = new Blob([JSON.stringify(exportClientSettings(), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "mycelium-settings.json";
  a.click();
  URL.revokeObjectURL(url);
}

export function GeneralPage() {
  const { theme, setTheme } = useTheme();
  const mounted = useIsClient();
  const desktop = useIsDesktop();
  const [send, setSend] = useClientSetting("general.send");
  const [agentAvatars, setAgentAvatars] = useClientSetting("general.agent-avatars");
  const [zone, setZone] = useClientSetting("general.time-zone");
  const fileRef = useRef<HTMLInputElement>(null);
  const [imported, setImported] = useState<string | null>(null);
  const here = mounted ? localZone() : "";
  const currentTheme = (mounted ? theme : undefined) ?? "dark";
  const { themes: customThemes, active: activeCustom } = useCustomThemes();

  const onImport = async (file: File | undefined) => {
    if (!file) return;
    try {
      importClientSettings(JSON.parse(await file.text()));
      setImported("Settings imported.");
    } catch {
      setImported("That file isn't a Mycelium settings file.");
    }
  };

  return (
    <SettingsPage
      title="General"
      scope={desktop ? "Saved in this app on this computer. Never sent to the hub." : "Saved in this browser. Never sent to the hub."}
      actions={
        <>
          <Button variant="outline" size="sm" onClick={exportFile}>
            Export
          </Button>
          <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
            Import
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(e) => void onImport(e.target.files?.[0])}
          />
        </>
      }
    >
      {imported && <Note>{imported}</Note>}
      <Section title="Appearance">
        <Row
          id="general.theme"
          label="Theme"
          help="Mycelium's own light or dark, a theme you know from your editor, or one of your own. Matching this computer picks Mycelium light or dark to suit it."
        >
          <Select
            aria-label="Theme"
            value={currentTheme === CUSTOM_THEME && activeCustom ? `${CUSTOM_PREFIX}${activeCustom.id}` : currentTheme}
            onChange={(e) => {
              const picked = e.target.value;
              if (picked.startsWith(CUSTOM_PREFIX)) {
                setClientSetting("appearance.custom-theme", picked.slice(CUSTOM_PREFIX.length));
                setTheme(CUSTOM_THEME);
              } else setTheme(picked);
            }}
          >
            <option value={SYSTEM}>Match this computer</option>
            <optgroup label="Light">
              {THEMES.filter((t) => t.mode === "light").map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Dark">
              {THEMES.filter((t) => t.mode === "dark").map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </optgroup>
            {customThemes.length > 0 && (
              <optgroup label="Yours">
                {customThemes.map((t) => (
                  <option key={t.id} value={`${CUSTOM_PREFIX}${t.id}`}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
            )}
          </Select>
        </Row>
        <CustomThemesRow />
        <Row
          id="general.agent-avatars"
          label="Agents appear as"
          help={
            agentAvatars === "creatures"
              ? "A small creature each agent's name picks, always the same one. People keep their initials."
              : "Their initials, like people."
          }
          changed={agentAvatars !== "creatures"}
          onReset={() => resetClientSetting("general.agent-avatars")}
          defaultLabel="Creatures"
        >
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5" aria-hidden>
              {["mycelium-coder", "voice-model", "schedule-ux"].map((h) => (
                <Monogram key={h} handle={h} className="size-6 text-[10px]" kind="agent" />
              ))}
            </span>
            <Segmented<AgentAvatars>
              label="Agents appear as"
              value={agentAvatars}
              options={[
                { value: "creatures", label: "Creatures" },
                { value: "initials", label: "Initials" },
              ]}
              onChange={setAgentAvatars}
            />
          </div>
        </Row>
      </Section>

      <Section title="Messages">
        <Row
          id="general.send"
          label="Send a message with"
          help={
            send === "enter"
              ? "Enter sends; Shift+Enter starts a new line."
              : "Enter starts a new line; the send key sends."
          }
          changed={send !== "enter"}
          onReset={() => resetClientSetting("general.send")}
          defaultLabel="Enter"
        >
          <Segmented<SendKey>
            label="Send a message with"
            value={send}
            options={[
              { value: "enter", label: "Enter" },
              { value: "mod-enter", label: <KbdChord size="xs" chord="mod+Enter" /> },
            ]}
            onChange={setSend}
          />
        </Row>
      </Section>

      <Section title="Time">
        <Row
          id="general.time-zone"
          label="Time zone"
          help="Where the board's Daily view starts and ends a day."
          changed={zone !== ""}
          onReset={() => resetClientSetting("general.time-zone")}
          defaultLabel={here ? `this computer's, ${here}` : "this computer's"}
        >
          <Select
            aria-label="Time zone"
            value={zone || here}
            onChange={(e) => setZone(e.target.value === here ? "" : e.target.value)}
          >
            {[...new Set([here, zone, ...COMMON_ZONES].filter(Boolean))].map((z) => (
              <option key={z} value={z}>
                {z === here ? `${z} (this computer)` : z}
              </option>
            ))}
          </Select>
        </Row>
      </Section>
    </SettingsPage>
  );
}
