// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { appCall, compareVersions, useApp, type AppRelease, type VersionsView } from "@/lib/desktop-app";
import { ActionError, useAppAction } from "./app-save";
import { Note, Row, Section, SettingsPage, Toggle } from "./settings-ui";

/**
 * The version running, release candidates on or off (which is also the
 * channel updates follow), and the releases to switch to. Switching asks on
 * the machine, downloads that release's signed update and restarts.
 */
export function AppVersionPage() {
  const { data: saved, mutate: remember } = useApp<VersionsView>("app_versions", { withRc: false });
  const rc = saved?.releaseCandidates ?? false;
  const { data: view, error: readError } = useApp<VersionsView>("app_versions", { withRc: rc });
  const { busy, error, run } = useAppAction();
  const [switching, setSwitching] = useState<string | null>(null);
  const switchTo = (tag: string) =>
    void run(() => appCall("switch_version", { tag })).then((ok) => ok && setSwitching(tag));
  const setRc = (on: boolean) =>
    void run(async () => {
      await appCall("set_update_channel", { releaseCandidates: on });
      await remember();
    });

  return (
    <SettingsPage
      title="Version"
      scope={
        view
          ? `Mycelium ${view.current}. The hub and the CLI inside the app change with it. A mycelium you installed separately for your terminal keeps its own version.`
          : "Which version of Mycelium this is."
      }
    >
      <Section title="Updates">
        <Row
          id="version.release-candidates"
          label="Offer release candidates"
          help="A release candidate is the next version, out early to try. With this on, they're listed below and updates offer the next one. Turn it off to go back to stable releases: you stay on what you have until the next stable one, or switch back below."
        >
          <Toggle label="Offer release candidates" checked={rc} onChange={setRc} disabled={busy || !saved} />
        </Row>
      </Section>
      <Section title="Switch to">
        {readError && <Note tone="error">{String(readError.message ?? readError)}</Note>}
        {/* A list kept from earlier, because GitHub couldn't be asked just now. */}
        {view?.note && <Note>{view.note}</Note>}
        {!view && !readError && <Row label="Reading releases…" />}
        {view?.releases.length === 0 && <Row label="No releases to switch to." />}
        {view?.releases.map((r) => (
          <Release key={r.tag} release={r} current={view.current} busy={busy || !!switching} onSwitch={() => switchTo(r.tag)} />
        ))}
      </Section>
      {switching && <Note>Downloading {switching.replace(/^v/, "")}. Mycelium restarts in it when it&apos;s ready.</Note>}
      <ActionError error={error} />
    </SettingsPage>
  );
}

function Release({ release: r, current, busy, onSwitch }: { release: AppRelease; current: string; busy: boolean; onSwitch: () => void }) {
  const [warned, setWarned] = useState(false);
  const here = r.version === current;
  const older = compareVersions(r.version, current) < 0;
  const tags = [here && "this version", r.prerelease && "release candidate", older && !here && "older"].filter(Boolean) as string[];
  const date = r.published ? new Date(r.published).toLocaleDateString() : "";
  return (
    <Row
      label={r.tag.replace(/^v/, "")}
      tag={tags.join(" · ") || undefined}
      help={date}
      below={
        warned && (
          <Note>
            This is older than the version you have. Rooms and settings a newer version saved may not open in it, and a
            hub elsewhere on a newer version may not work with it.
          </Note>
        )
      }
    >
      {!here && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => (older && !warned ? setWarned(true) : onSwitch())}
        >
          {older ? (warned ? `Switch to ${r.tag} anyway` : "Switch back") : "Switch"}
        </Button>
      )}
    </Row>
  );
}
