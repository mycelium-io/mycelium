// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * One hub setting on the Hub page, changeable when this caller may change the
 * hub: a switch, a choice, a number or a text with Save, or a key that can be
 * replaced or removed but never read back. A row the desktop app sets itself
 * links to the app's settings, and anyone else sees the value read-only.
 * Saving writes config.toml through the hub; it applies when the hub restarts.
 */

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { updateHubSettings, type HubEditing } from "@/lib/api";
import { settingHref, type SettingsPage } from "@/lib/client-settings";
import { HUB_EDITABLE, editMode, parseNumber } from "@/lib/hub-settings";
import { Confirm, Note, Row, Segmented, Toggle } from "./settings-ui";

/** The app's own Settings page where a setting the desktop app owns is changed. */
function appPageOf(key: string): SettingsPage {
  if (key.startsWith("voice.")) return "voice";
  if (key.startsWith("telemetry.")) return "privacy";
  if (key.startsWith("llm.")) return "model";
  return "connection";
}

/** A control for one key, and what goes under its row (an error, a confirm). */
export function useHubSettingControl({
  configKey,
  label,
  editing,
  display,
  onSaved,
  unit,
}: {
  configKey: string;
  label: string;
  editing: HubEditing | undefined;
  /** The value as shown to someone who can't change it here. */
  display: ReactNode;
  /** Re-read the hub's settings once a change is saved. */
  onSaved: () => void;
  /** Said after a number, like "seconds". */
  unit?: string;
}): { control: ReactNode; below: ReactNode; pending: boolean } {
  const [draft, setDraft] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mode = editMode(editing, configKey);
  const spec = HUB_EDITABLE[configKey];
  const value = editing?.values[configKey];
  const pending = editing?.pending.includes(configKey) ?? false;

  const save = async (next: unknown) => {
    setBusy(true);
    setError(null);
    try {
      await updateHubSettings({ [configKey]: next });
      setDraft(null);
      setReplacing(false);
      setRemoving(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (mode === "no" || !spec) return { control: display, below: null, pending: false };
  if (mode === "app") {
    return {
      control: (
        <>
          {display}
          <Link href={settingHref(appPageOf(configKey))} className="text-micro text-accent hover:underline">
            Change in this app&apos;s settings
          </Link>
        </>
      ),
      below: null,
      pending,
    };
  }

  const errorNote = error ? <Note tone="error">{error}</Note> : null;
  let control: ReactNode;
  let below: ReactNode = errorNote;

  if (spec.type === "bool") {
    control = <Toggle label={label} checked={Boolean(value)} disabled={busy} onChange={(v) => void save(v)} />;
  } else if (spec.type === "choice") {
    control = (
      <Segmented
        label={label}
        value={String(value ?? "")}
        options={(spec.choices ?? []).map((c) => ({ value: c, label: c }))}
        onChange={(v) => void save(v)}
      />
    );
  } else if (spec.type === "int" || spec.type === "number") {
    const current = value === undefined || value === null ? "" : String(value);
    const text = draft ?? current;
    const submit = () => {
      const parsed = parseNumber(spec, text);
      if ("error" in parsed) setError(parsed.error);
      else void save(parsed.value);
    };
    control = (
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Input
          type="number"
          aria-label={label}
          min={0}
          step={spec.type === "int" ? 1 : "any"}
          value={text}
          onChange={(e) => setDraft(e.target.value)}
          className="h-8 w-28"
        />
        {unit && <span className="text-micro text-muted-foreground">{unit}</span>}
        <Button type="submit" size="sm" variant="outline" disabled={busy || draft === null || draft === current}>
          Save
        </Button>
      </form>
    );
  } else if (spec.type === "text") {
    const current = typeof value === "string" ? value : "";
    const text = draft ?? current;
    control = (
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void save(text.trim());
        }}
      >
        <Input
          aria-label={label}
          value={text}
          placeholder="not set"
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          className="h-8 w-64 font-mono text-micro"
        />
        <Button type="submit" size="sm" variant="outline" disabled={busy || draft === null || draft.trim() === current}>
          Save
        </Button>
      </form>
    );
  } else {
    // A key: replaced or removed, never shown.
    const set = Boolean(value);
    if (replacing) {
      control = (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft?.trim()) void save(draft.trim());
          }}
        >
          <Input
            type="password"
            aria-label={`New ${label}`}
            autoComplete="off"
            autoFocus
            value={draft ?? ""}
            placeholder="Paste the new key"
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 w-64"
          />
          <Button type="submit" size="sm" variant="outline" disabled={busy || !draft?.trim()}>
            Save
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setReplacing(false);
              setDraft(null);
              setError(null);
            }}
          >
            Cancel
          </Button>
        </form>
      );
    } else {
      control = (
        <>
          <span className="text-label text-text">{set ? "set" : "not set"}</span>
          <Button size="sm" variant="outline" onClick={() => setReplacing(true)}>
            {set ? "Replace…" : "Add…"}
          </Button>
          {set && (
            <Button size="sm" variant="ghost" onClick={() => setRemoving(true)}>
              Remove
            </Button>
          )}
        </>
      );
    }
    if (removing) {
      below = (
        <>
          <Confirm
            title={`Remove the ${label}?`}
            confirmLabel="Remove it"
            busy={busy}
            onConfirm={() => void save("")}
            onCancel={() => setRemoving(false)}
          >
            Once the hub restarts, the hub&apos;s agents can&apos;t reach the model until a key is added again.
          </Confirm>
          {errorNote}
        </>
      );
    }
  }
  return { control, below, pending };
}

/** A hub setting's row: the control when this caller may change it, the value
 *  otherwise, and a tag once a saved change waits for the hub to restart. */
export function HubSettingRow({
  id,
  label,
  help,
  ...opts
}: {
  id?: string;
  label: string;
  help?: ReactNode;
} & Omit<Parameters<typeof useHubSettingControl>[0], "label">) {
  const { control, below, pending } = useHubSettingControl({ label, ...opts });
  return (
    <Row id={id} label={label} help={help} tag={pending ? "saved, applies after a restart" : undefined} below={below}>
      {control}
    </Row>
  );
}
