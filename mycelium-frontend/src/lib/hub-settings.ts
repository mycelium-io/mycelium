// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The hub settings the Hub page may change, and how each is edited. Frozen in
// contracts/hub-settings.json beside the hub's copy (services/hub_config.py)
// and asserted by hub-settings.contract.test.ts. The hub checks every change
// again, so this only decides which control a row draws.

import type { HubEditing } from "@/lib/api";

export type HubSettingType = "text" | "secret" | "bool" | "choice" | "int" | "number";

export interface HubSettingSpec {
  type: HubSettingType;
  choices?: readonly string[];
  /** Set by the desktop app's own switches, which win over config.toml. */
  app_owned?: boolean;
}

export const HUB_EDITABLE: Record<string, HubSettingSpec> = {
  "llm.model": { type: "text" },
  "llm.base_url": { type: "text" },
  "llm.api_key": { type: "secret" },
  "verifier.enabled": { type: "bool" },
  "voice.enabled": { type: "bool", app_owned: true },
  "voice.model": { type: "choice", choices: ["fast", "accurate"], app_owned: true },
  "voice.speech_url": { type: "text" },
  "voice.speech_model": { type: "text" },
  "voice.speech_voice": { type: "text" },
  "voice.speech_api_key": { type: "secret" },
  "telemetry.send_product_analytics": { type: "bool", app_owned: true },
  "worker.tools": { type: "bool" },
  "worker.pi_timeout_s": { type: "number" },
  "worker.max_turns_per_room": { type: "int" },
  "board.dependency_gate": { type: "bool" },
};

/** How a row may be changed by this caller: here, in the desktop app's own
 *  settings, or not at all. */
export function editMode(editing: HubEditing | undefined, key: string): "here" | "app" | "no" {
  if (!editing?.may_edit || !(key in HUB_EDITABLE)) return "no";
  return editing.app_owned.includes(key) ? "app" : "here";
}

/** The number typed in a number row, or why it can't be saved. */
export function parseNumber(spec: HubSettingSpec, text: string): { value: number } | { error: string } {
  const value = Number(text.trim());
  if (!text.trim() || !Number.isFinite(value)) return { error: "Type a number." };
  if (spec.type === "int" && !Number.isInteger(value)) return { error: "Type a whole number." };
  if (value <= 0) return { error: "Type a number more than 0." };
  return { value };
}
