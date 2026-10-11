// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import useSWR from "swr";
import { Skeleton } from "@/components/ui/skeleton";
import { hubSummary, StatusDot, TONE_COLOR } from "@/components/status-items";
import { useHubLabel } from "@/components/title-bar";
import { fetchHubSettings, fetchVoiceStatus } from "@/lib/api";
import { desktopMachine, settingsLink, useIsDesktop } from "@/lib/desktop";
import { DOCS_URL } from "@/lib/install";
import { useHubHealth } from "@/lib/use-status";
import { Note, Row, Section, SettingsPage, Value } from "./settings-ui";

/** What each channel identity tier means, in a line. */
const IDENTITY: Record<string, string> = {
  psk: "one shared key for every room",
  signerjwt: "each member signs as itself",
};

/** The config key a row comes from, so it can be found on the hub's machine. */
function Key({ name }: { name: string }) {
  return <code className="font-mono text-[11px] text-faint">{name}</code>;
}

function help(text: ReactNode, key: string): ReactNode {
  return (
    <>
      {text} <Key name={key} />
    </>
  );
}

function minutes(seconds: number): string {
  return seconds >= 60 ? `${Math.round(seconds / 60)} min` : `${seconds} s`;
}

/** The hub this window talks to and how it is set up. Nothing here changes
 *  from the page: a hub is set up on its own machine, and every value it holds
 *  is shared by everyone on it, so this page shows them and says where they're
 *  set. Keys are only ever "set" or "not set". */
export function HubPage() {
  const { data: health } = useHubHealth();
  const { data: hub } = useSWR("hub-settings", fetchHubSettings, { revalidateOnFocus: false });
  const { data: voice } = useSWR("voice-status", fetchVoiceStatus, { revalidateOnFocus: false });
  const label = useHubLabel();
  const desktop = useIsDesktop();
  const summary = hubSummary(health);
  const ownHub = desktop && label === `This ${desktopMachine()}`;
  const store = health?.storage?.host_path || health?.storage?.path || null;
  const identity = health?.identity?.mode ?? null;

  return (
    <SettingsPage
      title="Hub"
      scope="This hub, for everyone on it. Read-only here: it's set up on the hub's machine."
      actions={
        <span className="flex items-center gap-1.5 text-micro" style={{ color: TONE_COLOR[summary.tone] }}>
          <StatusDot tone={summary.tone} />
          {summary.text}
        </span>
      }
    >
      <div className="mt-5 rounded-lg border border-border bg-surface px-3 py-2.5 text-micro leading-relaxed text-muted-foreground">
        {ownHub ? (
          <>
            This {desktopMachine()} runs this hub.{" "}
            <a href={settingsLink()} className="text-accent hover:underline">
              Open Mycelium Settings
            </a>{" "}
            to change it. A change the hub reads at startup restarts it; agents connected to it reconnect on their own.
          </>
        ) : (
          <>
            Change these on the hub&apos;s machine with <code className="font-mono text-text">mycelium config set</code>{" "}
            and <code className="font-mono text-text">mycelium config apply</code>, then restart the hub. Agents
            connected to it reconnect on their own.{" "}
            <a href={`${DOCS_URL}/reference.html#configuration`} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              Every setting
            </a>
          </>
        )}
      </div>

      {health === undefined && <Skeleton className="mt-6 h-40 w-full rounded-xl" />}
      {health === null && <Note tone="error">The hub isn&apos;t answering.</Note>}

      {health && (
        <Section title="This hub">
          <Row label="Name">
            <Value>{label}</Value>
          </Row>
          {health.version && (
            <Row label="Version">
              <Value>{health.version}</Value>
            </Row>
          )}
          {store && (
            <Row label="Rooms are kept in">
              <Value mono>{store}</Value>
            </Row>
          )}
          {health.embedding?.model && (
            <Row label="Search model">
              <Value mono>{health.embedding.model}</Value>
            </Row>
          )}
        </Section>
      )}

      {hub && (
        <>
          <Section title="Model">
            <Row id="hub.model" label="Model the hub's agents use" help={help("Engines, personas and workers think with it.", "llm.model")}>
              <Value mono>{hub.model.model ?? "not set"}</Value>
            </Row>
            <Row id="hub.model-key" label="API key" help={help("The key itself never leaves the hub.", "llm.api_key")}>
              <Value risk={!hub.model.has_key && Boolean(hub.model.model)}>{hub.model.has_key ? "set" : "not set"}</Value>
            </Row>
            {hub.model.custom_endpoint && (
              <Row label="Endpoint" help={help("Answers at an address set by hand.", "llm.base_url")}>
                <Value>set</Value>
              </Row>
            )}
          </Section>

          <Section title="Workers">
            <Row
              id="hub.worker-tools"
              label="Workers can run commands"
              help={help("A worker edits and runs code in its own checkout, as the hub's user.", "worker.tools")}
            >
              <Value risk={hub.workers.tools}>{hub.workers.tools ? "on" : "off"}</Value>
            </Row>
            <Row id="hub.worker-timeout" label="Longest worker turn" help={help("A turn that runs longer is stopped.", "worker.pi_timeout_s")}>
              <Value>{minutes(hub.workers.turn_timeout_s)}</Value>
            </Row>
            <Row
              id="hub.worker-turns"
              label="Worker turns per room"
              help={help("A room can lower this in its own settings.", "worker.max_turns_per_room")}
            >
              <Value>{hub.workers.max_turns_per_room}</Value>
            </Row>
          </Section>

          <Section title="Board">
            <Row
              id="hub.dependency-gate"
              label="Tasks wait for what they depend on"
              help={help("A room can set this for itself.", "board.dependency_gate")}
            >
              <Value>{hub.dependency_gate ? "on" : "off"}</Value>
            </Row>
          </Section>

          <Section title="Access">
            <Row id="hub.sign-in" label="Sign-in required" help={help("Off, anyone who can reach the hub can use it.", "auth.enabled")}>
              <Value risk={!hub.sign_in}>{hub.sign_in ? "on" : "off"}</Value>
            </Row>
            {identity && (
              <Row label="Channel identity" help={IDENTITY[identity]}>
                <Value mono>{identity}</Value>
              </Row>
            )}
            <Row
              id="hub.personas-only"
              label="Patterns may only cast personas"
              help={help("A loaded scenario can't start a worker.", "patterns.personas_only")}
            >
              <Value>{hub.personas_only ? "on" : "off"}</Value>
            </Row>
            <Row
              id="hub.patterns-inline"
              label="Scenarios can be sent with a request"
              help={help("Otherwise only the hub's own pattern folder is used.", "patterns.allow_inline")}
            >
              <Value>{hub.patterns_inline ? "on" : "off"}</Value>
            </Row>
          </Section>

          <Section title="Voice and usage">
            <Row
              id="hub.voice"
              label="Voice"
              help={help(
                voice?.state === "not_downloaded" ? voice.detail || "The speech model is downloading." : "The message box's mic, transcribed on the hub.",
                "voice.enabled",
              )}
            >
              <Value>{hub.voice.enabled ? `on · ${hub.voice.model}` : "off"}</Value>
            </Row>
            <Row
              id="hub.share-usage"
              label="Share anonymous usage counts"
              help={help("Counts of tasks and runs, never names, rooms or text.", "telemetry.send_product_analytics")}
            >
              <Value>{hub.share_usage ? "on" : "off"}</Value>
            </Row>
          </Section>
        </>
      )}

      <Note>Secrets in the hub&apos;s config (keys, the channel secret, sign-in client secrets) never reach this page.</Note>
    </SettingsPage>
  );
}
