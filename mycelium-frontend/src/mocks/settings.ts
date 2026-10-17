// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The hub's settings and each room's, for the mock app. Room settings are
 *  kept for the session, like the mock's other writes, and checked the way the
 *  hub checks them (`app/services/room_settings.py`), so the settings page
 *  shows a real refusal for a value the hub would refuse. */

import type { HubSettings, RoomSetting } from "@/lib/api";
import { HUB_EDITABLE } from "@/lib/hub-settings";

export const HUB_SETTINGS: HubSettings = {
  model: { model: "anthropic/claude-sonnet-4-6", provider: "anthropic", has_key: true, custom_endpoint: false },
  experiences: [
    {
      id: "patterns-explorer",
      title: "Patterns Explorer",
      description: "Watch a team of agents work through a business scenario, start to finish.",
      open: "/patterns",
      unit: "business scenario",
      scenarios: 4,
    },
  ],
  personas_only: false,
  share_usage: false,
  workers: { tools: true, turn_timeout_s: 600, max_turns_per_room: 60 },
  dependency_gate: false,
  patterns_inline: true,
  sign_in: false,
  voice: { enabled: true, model: "fast", speech: true, speech_has_key: false },
  verifier: true,
  // A desktop hub: whoever reaches it may change it, and the app sets voice
  // and usage counts itself.
  editing: {
    may_edit: true,
    reason: null,
    can_restart: true,
    app_owned: ["voice.enabled", "voice.model", "telemetry.send_product_analytics"],
    pending: [],
    values: {},
  },
};

/** What the mock hub's settings are set to, as config.toml would hold them. */
const HUB_VALUES: Record<string, unknown> = {
  "llm.model": HUB_SETTINGS.model.model,
  "llm.base_url": "",
  "llm.api_key": HUB_SETTINGS.model.has_key,
  "verifier.enabled": HUB_SETTINGS.verifier,
  "voice.enabled": HUB_SETTINGS.voice.enabled,
  "voice.model": HUB_SETTINGS.voice.model,
  "voice.speech_url": "http://127.0.0.1:8880/v1",
  "voice.speech_model": "",
  "voice.speech_voice": "",
  "voice.speech_api_key": false,
  "telemetry.send_product_analytics": HUB_SETTINGS.share_usage,
  "worker.tools": HUB_SETTINGS.workers.tools,
  "worker.pi_timeout_s": HUB_SETTINGS.workers.turn_timeout_s,
  "worker.max_turns_per_room": HUB_SETTINGS.workers.max_turns_per_room,
  "board.dependency_gate": HUB_SETTINGS.dependency_gate,
};

/** GET /hub/settings: what it runs with, and what was saved since it started. */
export function hubSettingsRead(): HubSettings {
  return { ...HUB_SETTINGS, editing: { ...HUB_SETTINGS.editing, values: { ...HUB_VALUES } } };
}

/** PATCH /hub/settings, checked the way the hub checks it: every change before
 *  any is saved. */
export function saveHubSettings(changes: Record<string, unknown>): { status: number; body: unknown } {
  for (const [key, value] of Object.entries(changes)) {
    const spec = HUB_EDITABLE[key];
    if (!spec) return { status: 422, body: { detail: `Not a setting the app can change: ${key}` } };
    if (HUB_SETTINGS.editing.app_owned.includes(key)) {
      return { status: 422, body: { detail: `${key} is set in the app's own settings, which win over config.toml` } };
    }
    if (spec.type === "bool" && typeof value !== "boolean") return { status: 422, body: { detail: `${key} is on or off` } };
    if (spec.type === "int" || spec.type === "number") {
      if (typeof value !== "number") return { status: 422, body: { detail: `${key} is a number` } };
      if (spec.type === "int" && !Number.isInteger(value)) return { status: 422, body: { detail: `${key} is a whole number` } };
      if (value <= 0) return { status: 422, body: { detail: `${key} is more than 0` } };
    }
  }
  for (const [key, value] of Object.entries(changes)) {
    HUB_VALUES[key] = HUB_EDITABLE[key].type === "secret" ? Boolean(value) : value;
    if (!HUB_SETTINGS.editing.pending.includes(key)) HUB_SETTINGS.editing.pending.push(key);
  }
  HUB_SETTINGS.editing.pending.sort();
  return { status: 200, body: { saved: Object.keys(changes), pending: HUB_SETTINGS.editing.pending, restart_needed: true } };
}

/** POST /hub/restart: the hub comes back a moment later running what was saved. */
export function restartHubMock(): void {
  // The mock answers on the server, where there is no window.
  setTimeout(() => {
    const v = HUB_VALUES;
    HUB_SETTINGS.model = {
      ...HUB_SETTINGS.model,
      model: (v["llm.model"] as string) || null,
      has_key: Boolean(v["llm.api_key"]),
      custom_endpoint: Boolean(v["llm.base_url"]),
    };
    HUB_SETTINGS.verifier = Boolean(v["verifier.enabled"]);
    HUB_SETTINGS.workers = {
      tools: Boolean(v["worker.tools"]),
      turn_timeout_s: Number(v["worker.pi_timeout_s"]),
      max_turns_per_room: Number(v["worker.max_turns_per_room"]),
    };
    HUB_SETTINGS.dependency_gate = Boolean(v["board.dependency_gate"]);
    HUB_SETTINGS.editing.pending = [];
  }, 1_500);
}

interface Spec {
  id: string;
  kind: "bool" | "int" | "set";
  options: string[];
  hub: () => unknown;
  inherits: string | null;
  min: number | null;
  atMostHub: boolean;
}

const TABLE: Spec[] = [
  {
    id: "chat-board-moves",
    kind: "set",
    options: ["filed", "claimed", "released", "blocked", "unblocked", "expired", "resolved"],
    hub: () => ["filed", "resolved"],
    inherits: null,
    min: null,
    atMostHub: false,
  },
  {
    id: "dependency-gate",
    kind: "bool",
    options: [],
    hub: () => HUB_SETTINGS.dependency_gate,
    inherits: "board.dependency_gate",
    min: null,
    atMostHub: false,
  },
  {
    id: "worker-turns",
    kind: "int",
    options: [],
    hub: () => HUB_SETTINGS.workers.max_turns_per_room,
    inherits: "worker.max_turns_per_room",
    min: 1,
    atMostHub: true,
  },
];

interface Stored {
  value: unknown;
  reason: string;
  version: number;
  by: string;
  at: string;
}

const STORE = new Map<string, Map<string, Stored>>();

/** Rooms that open with a setting already set, so the page shows both states. */
const SEEDED: Record<string, Record<string, Stored>> = {
  checkout: {
    "worker-turns": {
      value: 40,
      reason: "Keep a swarm in this room short while the launch is on.",
      version: 2,
      by: "morgan",
      at: "2026-08-27T16:20:00Z",
    },
  },
};

function storeFor(room: string): Map<string, Stored> {
  let s = STORE.get(room);
  if (!s) {
    s = new Map(Object.entries(SEEDED[room] ?? {}));
    STORE.set(room, s);
  }
  return s;
}

function describe(room: string, spec: Spec): RoomSetting {
  const own = storeFor(room).get(spec.id);
  const hub = spec.hub();
  return {
    id: spec.id,
    kind: spec.kind,
    value: own ? own.value : hub,
    source: own ? "room" : spec.inherits ? "hub" : "default",
    hub_value: hub,
    options: spec.options,
    min: spec.min,
    max: spec.atMostHub ? (hub as number) : null,
    inherits: spec.inherits,
    reason: own?.reason ?? null,
    version: own?.version ?? null,
    updated_by: own?.by ?? null,
    updated_at: own?.at ?? null,
  };
}

export function roomSettings(room: string): RoomSetting[] {
  return TABLE.map((spec) => describe(room, spec));
}

/** Set one, or say why not, as the hub would. */
export function setRoomSettingMock(
  room: string,
  id: string,
  body: Record<string, unknown>,
): { ok: RoomSetting } | { status: number; message: string } {
  const spec = TABLE.find((s) => s.id === id);
  if (!spec) return { status: 404, message: `No room setting '${id}'` };
  const value = body.value;
  let stored: unknown = null;
  if (spec.kind === "bool" && typeof value === "boolean") stored = value;
  if (spec.kind === "int" && typeof value === "number" && Number.isInteger(value)) {
    const max = spec.atMostHub ? (spec.hub() as number) : Infinity;
    if (value >= (spec.min ?? -Infinity) && value <= max) stored = value;
  }
  if (spec.kind === "set" && Array.isArray(value) && value.every((v) => spec.options.includes(String(v)))) {
    stored = spec.options.filter((o) => value.includes(o));
  }
  if (stored === null) {
    const allowed =
      spec.kind === "bool"
        ? "true or false"
        : spec.kind === "int"
          ? `a whole number of at least ${spec.min}${spec.atMostHub ? ` and at most the hub's ${String(spec.hub())}` : ""}`
          : `a list drawn from ${spec.options.join(", ")}`;
    return { status: 422, message: `settings/${id} takes ${allowed}, not ${JSON.stringify(value)}` };
  }
  const prior = storeFor(room).get(id);
  const by = String(body.by ?? "user").replace(/^@/, "");
  storeFor(room).set(id, {
    value: stored,
    reason: String(body.reason ?? "") || `Set by @${by} from the settings page.`,
    version: (prior?.version ?? 0) + 1,
    by,
    at: new Date().toISOString(),
  });
  return { ok: describe(room, spec) };
}

export function resetRoomSettingMock(room: string, id: string): RoomSetting | null {
  const spec = TABLE.find((s) => s.id === id);
  if (!spec) return null;
  storeFor(room).delete(id);
  return describe(room, spec);
}
