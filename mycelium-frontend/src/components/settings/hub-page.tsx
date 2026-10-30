// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { hubSummary, StatusDot, TONE_COLOR } from "@/components/status-items";
import { useHubLabel } from "@/components/title-bar";
import { fetchHubSettings, fetchVoiceStatus, restartHub, type HubEditing } from "@/lib/api";
import { settingHref } from "@/lib/client-settings";
import { desktopMachine, useIsDesktop } from "@/lib/desktop";
import { DOCS_URL } from "@/lib/install";
import { useNetworkStatus } from "@/lib/room-data";
import { useHubHealth } from "@/lib/use-status";
import { HubSettingRow, useHubSettingControl } from "./hub-setting-control";
import { Note, Row, Section, SettingsPage, Value } from "./settings-ui";
import { VerifierSection } from "./verifier-section";

/** What each channel identity tier means, in a line. */
const IDENTITY: Record<string, string> = {
  psk: "one shared key for every room",
  signerjwt: "each member signs as itself",
};

/** How often to ask whether a restarting hub is back, and for how long. */
const RESTART_POLL_MS = 1_000;
const RESTART_WAIT_MS = 60_000;

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

/** The hub this window talks to and how it is set up. Someone who may change
 *  the hub (on a desktop hub, or a person when sign-in is on) changes its
 *  settings here; they are saved to config.toml and apply when it restarts.
 *  Anyone else sees them read-only, with where they're set. A key is only
 *  ever "set" or "not set". */
export function HubPage() {
  const { data: health } = useHubHealth();
  const { data: hub, mutate } = useSWR("hub-settings", fetchHubSettings, { revalidateOnFocus: false });
  const { data: voice } = useSWR("voice-status", fetchVoiceStatus, { revalidateOnFocus: false });
  const label = useHubLabel();
  const desktop = useIsDesktop();
  const summary = hubSummary(health);
  const ownHub = desktop && label === `This ${desktopMachine()}`;
  const store = health?.storage?.host_path || health?.storage?.path || null;
  const identity = health?.identity?.mode ?? null;
  const { network } = useNetworkStatus();
  const node = network?.coordination ?? null;
  const editing = hub?.editing;
  const mayEdit = editing?.may_edit ?? false;
  const reload = () => void mutate();
  const field = { editing, onSaved: reload };
  const verifier = useHubSettingControl({
    configKey: "verifier.enabled",
    label: "Verifier",
    display: null,
    ...field,
  });

  return (
    <SettingsPage
      title="Hub"
      scope={
        mayEdit
          ? "This hub, for everyone on it. Changes apply when the hub restarts."
          : "This hub, for everyone on it. Read-only here: it's set up on the hub's machine."
      }
      actions={
        <span className="flex items-center gap-1.5 text-micro" style={{ color: TONE_COLOR[summary.tone] }}>
          <StatusDot tone={summary.tone} />
          {summary.text}
        </span>
      }
    >
      <div className="mt-5 rounded-lg border border-border bg-surface px-3 py-2.5 text-micro leading-relaxed text-muted-foreground">
        {mayEdit ? (
          <>
            Changes are saved to the hub&apos;s <code className="font-mono text-text">config.toml</code> and apply when
            the hub restarts. Agents connected to it reconnect on their own.
            {ownHub && (
              <>
                {" "}
                Voice and usage counts are set on this app&apos;s{" "}
                <Link href={settingHref("voice")} className="text-accent hover:underline">
                  Voice
                </Link>{" "}
                and{" "}
                <Link href={settingHref("privacy")} className="text-accent hover:underline">
                  Privacy
                </Link>{" "}
                pages.
              </>
            )}
          </>
        ) : (
          <>
            {editing?.reason && <>{editing.reason} </>}
            Change these on the hub&apos;s machine with <code className="font-mono text-text">mycelium config set</code>{" "}
            and <code className="font-mono text-text">mycelium config apply</code>, then restart the hub. Agents
            connected to it reconnect on their own.{" "}
            <a href={`${DOCS_URL}/reference.html#configuration`} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              Every setting
            </a>
          </>
        )}
      </div>

      {editing && editing.pending.length > 0 && <PendingChanges editing={editing} onBack={reload} />}

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

      {node && (
        <Section
          title="Messaging node"
          note="The SLIM node carries every room's encrypted channel. A room's own channel is on its Room settings page."
        >
          <Row id="hub.node" label="Node" help={node.slim_enabled ? "Connected." : "This hub runs without it, so rooms have no channel."}>
            <Value mono risk={!node.slim_enabled}>{node.endpoint || "none"}</Value>
          </Row>
          <Row label="Rooms with a live channel">
            <Value>{node.channels_live}</Value>
          </Row>
          <Row
            label="Channels set up"
            help={node.provisions_failed > 0 ? "Some rooms' channels failed to set up. The hub's log says why." : undefined}
          >
            <Value risk={node.provisions_failed > 0}>
              {node.provisions_ok} ok{node.provisions_failed > 0 ? `, ${node.provisions_failed} failed` : ""}
            </Value>
          </Row>
          {node.invite_failures > 0 && (
            <Row label="Invites that failed" help="Members the node couldn't add to a room's channel.">
              <Value risk>{node.invite_failures}</Value>
            </Row>
          )}
        </Section>
      )}

      {hub && (
        <>
          <Section title="Engines' model">
            <HubSettingRow
              id="hub.model"
              label="Model"
              help={help(
                "Personas, workers, the synthesizer, the verifier and hello think with it. People's own agents don't. Written as provider/model.",
                "llm.model",
              )}
              configKey="llm.model"
              display={<Value mono>{hub.model.model ?? "not set"}</Value>}
              {...field}
            />
            <HubSettingRow
              id="hub.model-key"
              label="API key"
              help={help("The key itself never leaves the hub.", "llm.api_key")}
              configKey="llm.api_key"
              display={
                <Value risk={!hub.model.has_key && Boolean(hub.model.model)}>{hub.model.has_key ? "set" : "not set"}</Value>
              }
              {...field}
            />
            {(mayEdit || hub.model.custom_endpoint) && (
              <HubSettingRow
                id="hub.model-endpoint"
                label="Endpoint"
                help={help("An address set by hand, for a model served somewhere else. Empty uses the provider's own.", "llm.base_url")}
                configKey="llm.base_url"
                display={<Value>set</Value>}
                {...field}
              />
            )}
          </Section>

          <Section title="Workers">
            <HubSettingRow
              id="hub.worker-tools"
              label="Workers can run commands"
              help={help("A worker edits and runs code in its own checkout, as the hub's user.", "worker.tools")}
              configKey="worker.tools"
              display={<Value risk={hub.workers.tools}>{hub.workers.tools ? "on" : "off"}</Value>}
              {...field}
            />
            <HubSettingRow
              id="hub.worker-timeout"
              label="Longest worker turn"
              help={help("A turn that runs longer is stopped.", "worker.pi_timeout_s")}
              configKey="worker.pi_timeout_s"
              unit="seconds"
              display={<Value>{minutes(hub.workers.turn_timeout_s)}</Value>}
              {...field}
            />
            <HubSettingRow
              id="hub.worker-turns"
              label="Worker turns per room"
              help={help("A room can lower this in its own settings.", "worker.max_turns_per_room")}
              configKey="worker.max_turns_per_room"
              display={<Value>{hub.workers.max_turns_per_room}</Value>}
              {...field}
            />
          </Section>

          <Section title="Board">
            <HubSettingRow
              id="hub.dependency-gate"
              label="Tasks wait for what they depend on"
              help={help("A room can set this for itself.", "board.dependency_gate")}
              configKey="board.dependency_gate"
              display={<Value>{hub.dependency_gate ? "on" : "off"}</Value>}
              {...field}
            />
          </Section>

          <Section
            title="Access"
            note={mayEdit ? "Set on the hub's machine, since a change here could lock everyone out." : undefined}
          >
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
            <HubSettingRow
              id="hub.voice"
              label="Voice"
              help={help(
                voice?.state === "not_downloaded" ? voice.detail || "The speech model is downloading." : "The message box's mic, transcribed on the hub.",
                "voice.enabled",
              )}
              configKey="voice.enabled"
              display={<Value>{hub.voice.enabled ? `on · ${hub.voice.model}` : "off"}</Value>}
              {...field}
            />
            {mayEdit && !editing?.app_owned.includes("voice.model") && (
              <HubSettingRow
                id="hub.voice-model"
                label="Speech model"
                help={help("fast starts sooner; accurate makes fewer mistakes.", "voice.model")}
                configKey="voice.model"
                display={<Value>{hub.voice.model}</Value>}
                {...field}
              />
            )}
            <HubSettingRow
              id="hub.speech"
              label="Speech server"
              help={help(
                "Reads mentions aloud for anyone who turns it on in their notification settings. An OpenAI-style text-to-speech address you run; the hub asks it, so the app never needs to reach it.",
                "voice.speech_url",
              )}
              configKey="voice.speech_url"
              display={<Value>{hub.voice.speech ? "set" : "not set"}</Value>}
              {...field}
            />
            {mayEdit && (
              <>
                <HubSettingRow
                  id="hub.speech-model"
                  label="Speech model"
                  help={help("The model name the speech server expects. Empty sends none.", "voice.speech_model")}
                  configKey="voice.speech_model"
                  display={null}
                  {...field}
                />
                <HubSettingRow
                  id="hub.speech-voice"
                  label="Speech voice"
                  help={help("The voice it reads with. Empty sends none.", "voice.speech_voice")}
                  configKey="voice.speech_voice"
                  display={null}
                  {...field}
                />
              </>
            )}
            {(mayEdit || hub.voice.speech) && (
              <>
                <HubSettingRow
                  id="hub.speech-key"
                  label="Speech server key"
                  help={help("Sent as a bearer token. The key itself never leaves the hub.", "voice.speech_api_key")}
                  configKey="voice.speech_api_key"
                  display={<Value>{hub.voice.speech_has_key ? "set" : "not set"}</Value>}
                  {...field}
                />
              </>
            )}
            <HubSettingRow
              id="hub.share-usage"
              label="Share anonymous usage counts"
              help={help("Counts of tasks and runs, never names, rooms or text.", "telemetry.send_product_analytics")}
              configKey="telemetry.send_product_analytics"
              display={<Value>{hub.share_usage ? "on" : "off"}</Value>}
              {...field}
            />
          </Section>

          <VerifierSection
            configKey={(name) => <Key name={name} />}
            editor={mayEdit ? verifier : undefined}
          />
        </>
      )}

      <Note>Secrets in the hub&apos;s config (keys, the channel secret, sign-in client secrets) never reach this page.</Note>
    </SettingsPage>
  );
}

/** Saved changes waiting for the hub to restart, and the way to restart it. */
function PendingChanges({ editing, onBack }: { editing: HubEditing; onBack: () => void }) {
  const [restarting, setRestarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const count = editing.pending.length;

  // A restarted hub has nothing pending: once it answers that way, it's back.
  useEffect(() => {
    if (!restarting) return;
    const started = Date.now();
    const tick = window.setInterval(async () => {
      const now = await fetchHubSettings();
      if (now && now.editing.pending.length === 0) {
        window.clearInterval(tick);
        setRestarting(false);
        onBack();
      } else if (Date.now() - started > RESTART_WAIT_MS) {
        window.clearInterval(tick);
        setRestarting(false);
        setError("The hub hasn't come back yet. Mycelium's health check says why.");
      }
    }, RESTART_POLL_MS);
    return () => window.clearInterval(tick);
  }, [restarting, onBack]);

  const restart = async () => {
    setError(null);
    try {
      await restartHub();
      setRestarting(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div
      role="status"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2.5 text-micro"
    >
      <p className="min-w-0 flex-1 text-text">
        {restarting
          ? "Restarting the hub…"
          : `${count === 1 ? "1 change is" : `${count} changes are`} saved and will apply when the hub restarts.`}
        {!editing.can_restart && !restarting && (
          <span className="text-muted-foreground"> Restart it on its machine.</span>
        )}
        {error && <span className="block text-red">{error}</span>}
      </p>
      {editing.can_restart && (
        <Button size="sm" disabled={restarting} onClick={() => void restart()}>
          {restarting ? "Restarting…" : "Restart the hub"}
        </Button>
      )}
    </div>
  );
}
