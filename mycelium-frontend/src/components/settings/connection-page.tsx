// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useSyncExternalStore } from "react";
import { CopyField } from "@/components/ui/copy-field";
import { hubSummary, StatusDot, TONE_COLOR } from "@/components/status-items";
import { useHubLabel } from "@/components/title-bar";
import { desktopMachine, inviteLink, settingsLink, useIsDesktop } from "@/lib/desktop";
import { useHubHealth } from "@/lib/use-status";
import { Row, Section, SettingsPage, Value } from "./settings-ui";

const noSubscribe = () => () => {};

/** Which hub this window is using, and how someone else joins it. Choosing a
 *  different hub happens where the window is opened: in the desktop app, its
 *  own Settings window (it has to work while no hub answers); in a browser, by
 *  opening the other hub's address. */
export function ConnectionPage() {
  const desktop = useIsDesktop();
  const hub = useHubLabel();
  const { data: health } = useHubHealth();
  const origin = useSyncExternalStore(noSubscribe, () => window.location.origin, () => "");
  const summary = hubSummary(health);
  const ownHub = desktop && hub === `This ${desktopMachine()}`;

  return (
    <SettingsPage
      title="Connection"
      scope={desktop ? `Which hub this ${desktopMachine()} uses.` : "Which hub this browser is using."}
    >
      <Section title="The hub you're on">
        <Row label={hub} help={ownHub ? `This ${desktopMachine()} runs it. Your rooms are kept here.` : "Your rooms are kept on it."}>
          <span className="flex items-center gap-1.5 text-micro" style={{ color: TONE_COLOR[summary.tone] }}>
            <StatusDot tone={summary.tone} />
            {summary.text}
          </span>
        </Row>
        <Row id="connection.address" label="Address">
          <Value mono>{origin}</Value>
        </Row>
        {health?.version && (
          <Row label="Version">
            <Value>{health.version}</Value>
          </Row>
        )}
        {origin && (
          <Row
            id="connection.invite"
            label="Let someone else join"
            help={
              ownHub
                ? `Send them this link. It works for anyone who can reach this ${desktopMachine()}, on your network or through a tunnel.`
                : "Send them this link to open this hub's rooms."
            }
            below={<CopyField value={inviteLink(origin)} className="mt-2" />}
          />
        )}
      </Section>

      <Section title="Another hub">
        {desktop ? (
          <Row
            id="connection.switch"
            label="Use a different hub"
            help={`The app's own Settings window switches between running a hub on this ${desktopMachine()} and joining one elsewhere, and says what happens to the agents here before it does.`}
          >
            <a
              href={settingsLink()}
              className="rounded-md border border-border px-2.5 py-1 text-label text-text hover:bg-surface"
            >
              Switch hub…
            </a>
          </Row>
        ) : (
          <Row
            id="connection.switch"
            label="Use a different hub"
            help="Open the other hub's address in your browser. Each hub keeps its own rooms, and this browser remembers your settings for each one separately."
          />
        )}
      </Section>
    </SettingsPage>
  );
}
