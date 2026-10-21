// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { CopyField } from "@/components/ui/copy-field";
import { hubSummary, StatusDot, TONE_COLOR } from "@/components/status-items";
import { useHubLabel } from "@/components/title-bar";
import { desktopMachine, inviteLink, useIsDesktop } from "@/lib/desktop";
import { useHasAppSettings } from "@/lib/desktop-app";
import { useHubAddress } from "@/lib/hub-address";
import { useHubHealth } from "@/lib/use-status";
import { AppConnection } from "./app-connection";
import { Row, Section, SettingsPage, Value } from "./settings-ui";

/** Which hub this window is using, and how someone else joins it. In the
 *  desktop app, also where its rooms live (here, or a team's hub) and start
 *  at login; in a browser, another hub is another address. */
export function ConnectionPage() {
  const desktop = useIsDesktop();
  const app = useHasAppSettings();
  const hub = useHubLabel();
  const { data: health } = useHubHealth();
  const origin = useHubAddress();
  const summary = hubSummary(health);
  const ownHub = desktop && hub === `This ${desktopMachine()}`;

  return (
    <SettingsPage
      title={app ? "Hub and Connection" : "Connection"}
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

      {app ? (
        <AppConnection />
      ) : (
        <Section title="Another hub">
          <Row
            id="connection.switch"
            label="Use a different hub"
            help="Open the other hub's address in your browser. Each hub keeps its own rooms, and this browser remembers your settings for each one separately."
          />
        </Section>
      )}
    </SettingsPage>
  );
}
