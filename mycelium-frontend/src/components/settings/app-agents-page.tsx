// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { desktopMachine } from "@/lib/desktop";
import { appCall, saveAndRestart, tilde, useApp, withChange, type AppState, type Framework } from "@/lib/desktop-app";
import { ActionError, RestartSave, useAppAction } from "./app-save";
import { Note, Row, Section, SettingsPage, Value } from "./settings-ui";

function shortVersion(v: string | null): string {
  return v?.match(/\d+(?:\.\d+)+/)?.[0] ?? "";
}

/** The agent programs found on this machine, and the folder agents started
 *  from Mycelium may work in. */
export function AppAgentsPage() {
  const machine = desktopMachine();
  const { data: state } = useApp<AppState>("get_state");
  const { data: scan, error: scanError } = useApp<{ frameworks?: Framework[] } | Framework[]>("scan_agents");
  const found = (Array.isArray(scan) ? scan : (scan?.frameworks ?? [])).filter((f) => f.installed);
  const savedRoot = state?.settings?.roots[0] ?? state?.home ?? "";
  const [picked, setRoot] = useState<string | null>(null);
  const root = picked ?? savedRoot;
  const { busy, error, run } = useAppAction();
  const choose = () =>
    void run(async () => {
      const picked = await appCall<string | null>("pick_folder", { start: root || null });
      if (picked) setRoot(picked);
    });
  const save = () => {
    if (!state?.settings) return;
    void run(() => saveAndRestart(withChange(state.settings!, { roots: [root] })));
  };
  const herdr = state?.herdr;

  return (
    <SettingsPage title="Agents" scope={`The agent programs on this ${machine}, and where agents may work.`}>
      <Section title="Found here">
        {scanError && <Note tone="error">{String(scanError.message ?? scanError)}</Note>}
        {!scan && !scanError && <Row label="Looking…" />}
        {found.map((f) => (
          <Row key={f.id} label={f.name} help={f.launchable ? undefined : "herdr can't start this one."}>
            <Value>{shortVersion(f.version)}</Value>
          </Row>
        ))}
        {scan && found.length === 0 && (
          <Row label="No agent apps found" help="Install one, like Claude Code, to start agents from Mycelium." />
        )}
        {herdr && (
          <Row label="herdr" help="Where agents run.">
            <Value risk={!herdr.path}>{herdr.bundled ? "included" : herdr.path ? "installed" : "missing"}</Value>
          </Row>
        )}
      </Section>
      <Section title="Working folder">
        <Row
          id="agents.folder"
          label={root && state ? tilde(root, state.home) : "…"}
          help="Agents started from Mycelium can only work in this folder."
        >
          <Button variant="outline" size="sm" onClick={choose} disabled={busy}>
            Choose…
          </Button>
        </Row>
      </Section>
      {root && root !== savedRoot && (
        <div className="mt-4 flex items-center justify-end gap-3">
          <RestartSave onSave={save} busy={busy} />
        </div>
      )}
      <ActionError error={error} />
    </SettingsPage>
  );
}
