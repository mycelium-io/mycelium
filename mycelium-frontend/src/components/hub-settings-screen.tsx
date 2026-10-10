// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import type { ReactNode } from "react";
import { useSyncExternalStore } from "react";
import useSWR from "swr";
import { fetchVoiceStatus } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { hubSummary, StatusDot, TONE_COLOR } from "@/components/status-items";
import { useHubLabel } from "@/components/title-bar";
import { desktopMachine, settingsLink, useIsDesktop } from "@/lib/desktop";
import { DOCS_URL } from "@/lib/install";
import { useHubHealth } from "@/lib/use-status";

const noSubscribe = () => () => {};

/** What each channel identity tier means, in a line. */
const IDENTITY: Record<string, string> = {
  psk: "one shared key for every room",
  signerjwt: "each member signs as itself",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-1 px-1 text-micro font-medium text-faint">{title}</h3>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2 rounded-xl border border-border px-4 py-3 text-label">
        {children}
      </dl>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-text">{children}</dd>
    </>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return (
    <span className="block truncate font-mono text-micro" title={typeof children === "string" ? children : undefined}>
      {children}
    </span>
  );
}

/** Whether the hub transcribes the message box's mic, and why not when it doesn't. */
function VoiceRow() {
  const { data: voice } = useSWR("voice-status", fetchVoiceStatus, { revalidateOnFocus: false });
  if (!voice) return null;
  const [state, why] =
    voice.state === "ready"
      ? ["on", "English, transcribed on the hub"]
      : voice.state === "not_downloaded"
        ? ["on", voice.detail || "the speech model is downloading"]
        : voice.detail.includes("voice.enabled")
          ? ["off", "turn it on with voice.enabled"]
          : ["unavailable", voice.detail];
  return (
    <Row label="Voice">
      {state}
      <span className="text-muted-foreground"> · {why}</span>
    </Row>
  );
}

/** The hub this page talks to and how it is set up, read off its `/health`.
 *  Nothing here is changed from the browser: a hub is configured on its own
 *  machine, which inside the desktop app is the app's Settings window. */
export function HubSettingsScreen() {
  const { data: health } = useHubHealth();
  const hub = useHubLabel();
  const desktop = useIsDesktop();
  const origin = useSyncExternalStore(noSubscribe, () => window.location.origin, () => "");
  const summary = hubSummary(health);
  const ownHub = desktop && hub === `This ${desktopMachine()}`;
  const store = health?.storage?.host_path || health?.storage?.path || null;
  const identity = health?.identity?.mode ?? null;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        <div className="flex items-start gap-3 px-1">
          <div className="min-w-0">
            <h2 className="text-body font-medium text-text">Hub</h2>
            <p className="mt-1 max-w-2xl text-micro leading-relaxed text-muted-foreground">
              The hub keeps your rooms, their memory and their channels, and runs the room&apos;s
              engines. Every machine and browser connected to it reads the same rooms.
            </p>
          </div>
          <span
            className="ml-auto flex flex-shrink-0 items-center gap-1.5 text-micro"
            style={{ color: TONE_COLOR[summary.tone] }}
          >
            <StatusDot tone={summary.tone} />
            {summary.text}
          </span>
        </div>

        {health === undefined && <Skeleton className="mt-6 h-40 w-full rounded-xl" />}
        {health === null && (
          <p className="mt-6 px-1 text-label text-muted-foreground">
            The hub at <span className="font-mono text-text">{origin}</span> is not answering. On its
            machine, opening the Mycelium app starts it, or{" "}
            <code className="font-mono text-text">mycelium up</code> for a Docker hub.
          </p>
        )}
        {health && (
          <>
            <Section title="This hub">
              <Row label="Name">{hub}</Row>
              <Row label="Address">
                <Mono>{origin}</Mono>
              </Row>
              {health.version && <Row label="Version">{health.version}</Row>}
              {health.coordination?.channels_live != null && (
                <Row label="Live channels">{health.coordination.channels_live}</Row>
              )}
              <VoiceRow />
            </Section>

            <Section title="Storage">
              {store && (
                <Row label="Folder">
                  <Mono>{store}</Mono>
                </Row>
              )}
              {health.embedding?.model && (
                <Row label="Search model">
                  <Mono>{health.embedding.model}</Mono>
                </Row>
              )}
            </Section>

            <Section title="Access">
              {identity && (
                <Row label="Channel identity">
                  <span className="font-mono text-micro">{identity}</span>
                  {IDENTITY[identity] && <span className="text-muted-foreground"> · {IDENTITY[identity]}</span>}
                </Row>
              )}
              {health.auth && (
                <Row label="Sign-in">
                  {health.auth.enabled ? "required" : "off"}
                  <span className="text-muted-foreground">
                    {health.auth.enabled ? " · callers present a token" : " · anyone who can reach it can use it"}
                  </span>
                </Row>
              )}
            </Section>
          </>
        )}

        <div className="mt-6 border-t border-border px-1 pt-3 text-micro text-muted-foreground">
          {ownHub ? (
            <>
              This {desktopMachine()} runs this hub.{" "}
              <a href={settingsLink()} className="text-accent hover:underline">
                Open Mycelium Settings
              </a>{" "}
              to change it.
            </>
          ) : (
            <>
              These are set on the hub&apos;s machine, with{" "}
              <code className="font-mono text-text">mycelium config set</code> then{" "}
              <code className="font-mono text-text">mycelium config apply</code>.{" "}
              <a
                href={`${DOCS_URL}/reference.html#configuration`}
                target="_blank"
                rel="noreferrer"
                className="text-accent hover:underline"
              >
                Every setting
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
