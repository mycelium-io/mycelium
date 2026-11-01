// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The Verifier on the Hub page: whether it's on (set in the hub's config, so
 * shown here with the command), which rooms it checks (the ones that added
 * it), and Learn, which costs model tokens and so starts only when asked.
 */

import { useState } from "react";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { fetchVerifierSettings, startVerifierLearn, type VerifierSettings } from "@/lib/api";
import { Row, Section, Value } from "./settings-ui";

/** How often to re-read while Learn runs, so its progress moves. */
const LEARNING_POLL_MS = 2_000;

function usd(amount: number): string {
  return amount < 1.5 ? "About $1" : `About $${Math.round(amount)}`;
}

export function VerifierSection({
  configKey,
  editor,
}: {
  configKey: (name: string) => React.ReactNode;
  /** Its on/off switch and what goes under it, when this caller may change
   *  the hub (`useHubSettingControl`); shown read-only otherwise. */
  editor?: { control: React.ReactNode; below: React.ReactNode; pending: boolean };
}) {
  const { data, mutate } = useSWR("verifier-settings", fetchVerifierSettings, {
    revalidateOnFocus: false,
    refreshInterval: (latest?: VerifierSettings) => (latest?.learning.state === "running" ? LEARNING_POLL_MS : 0),
  });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!data) return null;

  const learn = async () => {
    setStarting(true);
    setError(null);
    try {
      await mutate(await startVerifierLearn(), { revalidate: false });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start learning");
    } finally {
      setStarting(false);
    }
  };

  const { learning, estimate } = data;
  const running = learning.state === "running";
  const rooms = data.rooms.length ? data.rooms.join(" · ") : "none yet";

  return (
    <Section
      title="Verifier"
      note="Checks what agents say about approvals and merges against the room's records. Nothing to download."
    >
      <Row
        id="hub.verifier"
        label="Verifier"
        help={
          <>
            {data.enabled || editor
              ? "Adds a short note under a message when it can't find what an agent claimed, like an approval."
              : "Off. Turn it on on the hub's machine with mycelium config set verifier.enabled true."}{" "}
            {configKey("verifier.enabled")}
          </>
        }
        tag={editor?.pending ? "saved, applies after a restart" : undefined}
        below={editor?.below}
      >
        {editor ? editor.control : <Value>{data.enabled ? "on" : "off"}</Value>}
      </Row>
      <Row
        id="hub.verifier-rooms"
        label="Rooms it checks"
        help="Only rooms that add it, from Add member or with /engine verifier."
      >
        <Value>{rooms}</Value>
      </Row>
      {running ? (
        <Row
          id="hub.verifier-learn"
          label="Learning from your team"
          help={`${learning.done.toLocaleString()} of ${learning.total.toLocaleString()} messages read.`}
          below={<Progress done={learning.done} total={learning.total} />}
        >
          <Value>{learning.total ? `${Math.round((learning.done / learning.total) * 100)}%` : "starting"}</Value>
        </Row>
      ) : data.using === "learned" ? (
        <Row
          id="hub.verifier-learn"
          label="Learned from your team"
          help="Fitted to past messages in the rooms it checks. Learn again to include newer ones."
        >
          <Value>{`${(data.learned ?? 0).toLocaleString()} messages`}</Value>
        </Row>
      ) : (
        <Row
          id="hub.verifier-learn"
          label="Learn from your team"
          help={
            learning.state === "failed"
              ? `Learning stopped: ${learning.error ?? "something went wrong"}.`
              : data.rooms.length === 0
                ? "Add it to a room first. It only learns from rooms that added it."
                : `Reads ${estimate.messages.toLocaleString()} past messages in the rooms it checks once, so it learns how your agents write. ${usd(estimate.approx_usd)}.`
          }
          below={error ? <p className="mt-1 text-micro text-red">{error}</p> : undefined}
        >
          <Button
            size="xs"
            variant="outline"
            disabled={starting || data.rooms.length === 0}
            onClick={() => void learn()}
          >
            {learning.state === "failed" ? "Try again" : "Start…"}
          </Button>
        </Row>
      )}
    </Section>
  );
}

function Progress({ done, total }: { done: number; total: number }) {
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="mt-2 h-1 overflow-hidden rounded-full bg-hairline"
    >
      <div className="h-full bg-accent transition-[width]" style={{ width: `${percent}%` }} />
    </div>
  );
}
