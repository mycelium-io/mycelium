// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The app's own screens: the first-run wizard, Settings, the wait while
// Mycelium starts, and the health check. Once the supervisor says the room UI
// is up, the app points this window at it and these pages are gone.

import "./style.css";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Mode = "hub" | "client";
type State = "starting" | "running" | "stopped" | "failed" | "disabled" | "waiting";

interface Settings {
  mode: Mode;
  hubUrl: string | null;
  roots: string[];
  shareUsage?: boolean;
}

interface Found {
  name: string;
  path: string | null;
  bundled: boolean;
}

/** A hub on this Mac, as `mycelium.hubs` found it. */
interface HubSeen {
  source: "docker" | "process" | "port";
  owner: string;
  description: string;
  version: string | null;
  data_path: string | null;
  dev_build: boolean;
  port: number | null;
  project: string | null;
  container: string | null;
  image: string | null;
  pid: number | null;
}

/** A hub the app didn't start is on its port: use it, or stop it and start the app's own. */
interface HubQuestion {
  kind: "existing_hub";
  hub: HubSeen;
  /** False: it writes somewhere other than the app's data folder. Null: can't tell. */
  same_store: boolean | null;
  data_dir: string;
  app_version: string;
}

interface Status {
  type: "status";
  mode: Mode;
  ui_url?: string;
  api_url?: string;
  components: Record<string, { state: State; detail?: string | null }>;
  /** More than one hub here, a hub on someone else's store, an old one. */
  warnings?: string[];
  question?: HubQuestion | null;
}

interface Snapshot {
  settings: Settings | null;
  status: Status | null;
  lastError: string | null;
  mycelium: Found;
  herdr: Found;
  home: string;
}

interface Framework {
  id: string;
  name: string;
  version: string | null;
  installed: boolean;
  launchable: boolean;
}

interface PathSetup {
  linked: string[];
  skipped: string[];
  onPath: boolean;
  line: string;
}

/** `mycelium desktop model`: the key itself never comes back, only its last four. */
interface ModelView {
  model: string | null;
  base_url: string | null;
  has_key: boolean;
  key_hint: string | null;
}

/** `mycelium desktop experiences`: a ready-made room to explore, and whether it's here. */
interface Experience {
  id: string;
  title: string;
  description: string;
  /** Where it opens in the room UI. */
  open: string;
  /** What one scenario in it is called, for the count. */
  unit: string;
  added: boolean;
  scenarios: number;
}

/** `mycelium hub settings --json`: what a hub is set up with. Read-only, no key in it. */
interface HubSettings {
  model: { model: string | null; provider: string | null; has_key: boolean; custom_endpoint: boolean };
  experiences: { id: string; title: string; description: string; open: string; unit: string; scenarios: number }[];
  personas_only: boolean;
  share_usage: boolean;
}

interface Check {
  section: string;
  name: string;
  status: string;
  message: string;
  details: string[];
}

type ProviderId = "anthropic" | "openai" | "openrouter" | "ollama" | "custom";

interface Provider {
  id: ProviderId;
  name: string;
  /** Suggestions, the first the default; the same ones `mycelium install` offers. */
  models: string[];
  /** The key field's placeholder; null for a provider that needs no key. */
  key: string | null;
  /** Where to get a key, said in the field's hint. */
  keyFrom?: string;
  /** Where it answers, for a provider the hub can't find on its own. */
  baseUrl?: string;
}

const PROVIDERS: Provider[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    models: ["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-6", "anthropic/claude-haiku-4-5"],
    key: "sk-ant-…",
    keyFrom: "console.anthropic.com, under API keys",
  },
  {
    id: "openai",
    name: "OpenAI",
    models: ["openai/gpt-4.1", "openai/gpt-4o", "openai/gpt-4o-mini", "openai/o3"],
    key: "sk-…",
    keyFrom: "platform.openai.com, under API keys",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    models: ["openrouter/anthropic/claude-sonnet-4-6"],
    key: "sk-or-…",
    keyFrom: "openrouter.ai, under Keys",
  },
  {
    id: "ollama",
    name: "Ollama",
    models: ["ollama/llama3.3", "ollama/mistral", "ollama/qwen2.5"],
    key: null,
    baseUrl: "http://localhost:11434",
  },
  { id: "custom", name: "Other", models: [], key: "If it needs one", baseUrl: "" },
];

/** What the model is for, in our own docs: which of Mycelium's agents use it. */
const MODELS_DOC = "https://mycelium-io.github.io/mycelium/guides.html#models";

function providerOf(model: string | null): Provider {
  const prefix = (model ?? "").split("/")[0];
  return PROVIDERS.find((p) => p.id === prefix) ?? (model ? PROVIDERS[PROVIDERS.length - 1] : PROVIDERS[0]);
}

const inApp = "__TAURI_INTERNALS__" in window;
const app = document.getElementById("app")!;

// ── outside the app (a browser preview): a made-up machine so pages still draw ──

const previewAs = new URLSearchParams(location.search).get("preview");
const previewSetUp = previewAs === "settings" || previewAs === "client" || previewAs === "hub-question";
// ?preview=hub-question: a leftover Docker hub on the app's port, put to the person.
const PREVIEW_QUESTION: Status | null =
  previewAs === "hub-question"
    ? {
        type: "status",
        mode: "hub",
        components: {
          herdr: { state: "stopped" },
          slim: { state: "stopped" },
          hub: { state: "waiting", detail: "another hub is on port 8000" },
          ui: { state: "stopped" },
          runner: { state: "stopped" },
        },
        question: {
          kind: "existing_hub",
          hub: {
            source: "docker",
            owner: "Docker project `mycelium-concord-eval`, `mycelium-backend:dev`",
            description: "",
            version: "0.1.0",
            data_path: "/Users/you/.mycelium-concord-eval",
            dev_build: true,
            port: 8000,
            project: "mycelium-concord-eval",
            container: "mycelium-eval-backend",
            image: "mycelium-backend:dev",
            pid: null,
          },
          same_store: false,
          data_dir: "/Users/you/.mycelium",
          app_version: "3.0.22",
        },
      }
    : null;
const PREVIEW: Snapshot = {
  settings: previewSetUp
    ? previewAs === "client"
      ? { mode: "client", hubUrl: "https://hub.example.com", roots: ["/Users/you/code"], shareUsage: false }
      : { mode: "hub", hubUrl: null, roots: ["/Users/you/code"], shareUsage: false }
    : null,
  status: PREVIEW_QUESTION,
  lastError: null,
  mycelium: { name: "mycelium", path: "/Applications/Mycelium.app/Contents/MacOS/mycelium", bundled: true },
  herdr: { name: "herdr", path: "/Applications/Mycelium.app/Contents/MacOS/herdr", bundled: true },
  home: "/Users/you",
};
const PREVIEW_AGENTS: Framework[] = [
  { id: "claude", name: "Claude Code", version: "2.1.280", installed: true, launchable: true },
  { id: "opencode", name: "OpenCode", version: "1.18.23", installed: true, launchable: true },
];
const PREVIEW_MODEL: ModelView = previewSetUp
  ? { model: "anthropic/claude-sonnet-4-6", base_url: null, has_key: true, key_hint: "a1b2" }
  : { model: null, base_url: null, has_key: false, key_hint: null };
let previewExperiences: Experience[] = [
  {
    id: "patterns-explorer",
    title: "Patterns Explorer",
    description: "Watch a team of agents work through a business scenario, start to finish.",
    open: "/patterns",
    unit: "business scenario",
    added: previewSetUp,
    scenarios: previewSetUp ? 3 : 0,
  },
];
const PREVIEW_HUB: HubSettings = {
  model: { model: "anthropic/claude-sonnet-4-6", provider: "anthropic", has_key: true, custom_endpoint: false },
  experiences: [
    {
      id: "patterns-explorer",
      title: "Patterns Explorer",
      description: "Watch a team of agents work through a business scenario, start to finish.",
      open: "/patterns",
      unit: "business scenario",
      scenarios: 3,
    },
  ],
  personas_only: true,
  share_usage: false,
};
const PREVIEW_CHECKS: Check[] = [
  { section: "This Mac", name: "Hub", status: "ok", message: "answering at http://127.0.0.1:8000", details: [] },
  { section: "Agents", name: "herdr", status: "ok", message: "running (0.9.1)", details: [] },
  {
    section: "Models",
    name: "LLM connectivity",
    status: previewSetUp ? "ok" : "warning",
    message: previewSetUp ? "anthropic/claude-sonnet-4-6: completion probe succeeded" : "Not configured",
    details: previewSetUp ? [] : ["Choose a model and add its key in Settings (⌘,)"],
  },
];

async function snapshot(): Promise<Snapshot> {
  return inApp ? invoke<Snapshot>("get_state") : PREVIEW;
}

// ── small helpers ───────────────────────────────────────────────────────────

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  ...children: (Node | string | null | false)[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c) node.append(c);
  return node;
}

function tilde(path: string, home: string): string {
  return home && path.startsWith(home) ? "~" + path.slice(home.length) : path;
}

function shortVersion(v: string | null): string {
  return v?.match(/\d+(?:\.\d+)+/)?.[0] ?? "";
}

/** A link out of the app: opened in a new tab, which the app hands to the default browser. */
function outLink(href: string, text: string): HTMLAnchorElement {
  return el("a", { href, target: "_blank", rel: "noreferrer" }, text);
}

function head(sub: string): HTMLElement {
  return el(
    "div",
    { class: "card-head" },
    el("div", { class: "brand" }, el("img", { class: "brand-mark", src: "/mark.png", alt: "" }), "Mycelium"),
    el("p", { class: "sub" }, sub),
  );
}

function checkbox(id: string, checked: boolean, onChange: (on: boolean) => void): HTMLInputElement {
  const box = el("input", { type: "checkbox", class: "toggle", id });
  box.checked = checked;
  box.addEventListener("change", () => onChange(box.checked));
  return box;
}

/** What the person has chosen so far: the wizard fills it in, Settings starts from what's saved. */
interface Choices {
  mode: Mode;
  hubUrl: string;
  root: string;
  shareUsage: boolean;
  /** Whether to install herdr's integrations: asked on first run only, so
   *  absent from Settings, which leaves the answer given then alone. */
  restore?: boolean;
}

function choicesFrom(snap: Snapshot): Choices {
  return {
    mode: snap.settings?.mode ?? "hub",
    hubUrl: snap.settings?.hubUrl ?? "",
    root: tilde(snap.settings?.roots[0] ?? snap.home, snap.home),
    shareUsage: snap.settings?.shareUsage ?? false,
  };
}

function settingsOf(c: Choices): Settings {
  return {
    mode: c.mode,
    hubUrl: c.mode === "client" ? c.hubUrl.trim() : null,
    roots: [c.root.trim()],
    shareUsage: c.mode === "hub" && c.shareUsage,
  };
}

/** Save and (re)start what the app runs, then show it starting. */
async function startWith(c: Choices, model: Record<string, string> | null): Promise<void> {
  if (!inApp) return;
  // Saved first, so the hub that starts reads it.
  if (model && c.mode === "hub") await invoke<ModelView>("save_model", { model });
  const setup = await invoke<PathSetup>("start", { settings: settingsOf(c) });
  if (c.restore !== undefined) {
    // Remembered either way, so the app doesn't ask again when it starts.
    void invoke("herdr_integrations", { install: c.restore }).catch((e) => console.warn("herdr's integrations:", e));
  }
  await loading(setup);
}

// ── the pieces: each written once, shown by the wizard a step at a time and
// by Settings a section at a time ─────────────────────────────────────────────

/** Where rooms live: on this Mac, or on a team's hub at an address.
 *  ``onModeChange`` fires when the choice changes, not on every keystroke of
 *  the address, so a redraw it causes never takes the cursor out of the field. */
function placePiece(c: Choices, onModeChange: () => void): { el: HTMLElement; problem: () => string | null } {
  const hubField = el("input", {
    class: "field mono",
    placeholder: "https://hub.example.com",
    spellcheck: "false",
    autocapitalize: "none",
    "aria-label": "Hub address",
  });
  hubField.value = c.hubUrl;
  hubField.addEventListener("input", () => {
    c.hubUrl = hubField.value;
  });
  const hubRow = el("div", { class: "indent" }, el("div", { class: "label" }, "The hub's address"), hubField);

  const choice = (value: Mode, title: string, sub: string) => {
    const b = el(
      "button",
      { class: "choice stacked", type: "button", role: "radio" },
      el("strong", {}, title),
      el("span", {}, sub),
      el("i", { class: "radio", "aria-hidden": "true" }),
    );
    b.addEventListener("click", () => {
      if (c.mode === value) return;
      c.mode = value;
      render();
      onModeChange();
    });
    return b;
  };
  const here = choice("hub", "On this Mac", "Everything stays on this Mac. Good for trying it out or giving a demo.");
  const team = choice("client", "On my team's hub", "Join rooms someone else hosts. You'll need the hub's address.");
  const render = () => {
    here.setAttribute("aria-checked", String(c.mode === "hub"));
    team.setAttribute("aria-checked", String(c.mode === "client"));
    hubRow.hidden = c.mode !== "client";
  };
  render();
  return {
    el: el("div", { class: "piece" }, el("div", { class: "choices column", role: "radiogroup", "aria-label": "Where rooms live" }, here, team), hubRow),
    problem: () => (c.mode === "client" && !c.hubUrl.trim() ? "Enter the hub's address." : null),
  };
}

/**
 * The model Mycelium's own agents (the mediator, personas, the note-taker)
 * think with. The saved key is never shown, only its last four characters;
 * leaving the field empty keeps it. In the wizard the model name stays out of
 * the way behind a Change link; in Settings it's a field.
 */
async function modelPiece(variant: "wizard" | "settings"): Promise<{ el: HTMLElement; value: () => Record<string, string>; summary: () => string }> {
  let saved = PREVIEW_MODEL;
  try {
    if (inApp) saved = await invoke<ModelView>("get_model");
  } catch {
    // Unread settings start from the defaults; saving still writes them.
  }
  let provider = providerOf(saved.model);
  let typedKey = "";

  const seg = el("div", { class: "seg", role: "radiogroup", "aria-label": "Provider" });
  const segButtons = PROVIDERS.map((p) => {
    const b = el("button", { type: "button", role: "radio" }, p.name);
    b.addEventListener("click", () => {
      provider = p;
      modelField.value = p.models[0] ?? "";
      baseField.value = p.baseUrl ?? "";
      render();
    });
    seg.append(b);
    return { p, b };
  });

  const keyField = el("input", {
    class: "field mono",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    "aria-label": "API key",
  });
  keyField.addEventListener("input", () => {
    typedKey = keyField.value.trim();
  });
  const keyHint = el("p", { class: "hint" });
  // A saved key is a state, not text in the field: "Key saved", and Replace
  // to paste another. It belongs to the provider it was saved for.
  const savedFor = providerOf(saved.model).id;
  let replacing = false;
  const replace = el("button", { type: "button", class: "link" }, "Replace");
  const keep = el("button", { type: "button", class: "link" }, "Keep the saved key");
  const keySaved = el("div", { class: "key-saved" }, el("span", { class: "tick", "aria-hidden": "true" }, "✓"), "Key saved", replace);
  const keyEntry = el("div", { class: "key-entry" }, keyField, keep);
  replace.addEventListener("click", () => {
    replacing = true;
    render();
    keyField.focus();
  });
  keep.addEventListener("click", () => {
    replacing = false;
    typedKey = "";
    keyField.value = "";
    render();
  });
  const keyRow = el("div", {}, el("div", { class: "label" }, "API key"), keySaved, keyEntry, keyHint);

  const baseField = el("input", {
    class: "field mono",
    spellcheck: "false",
    autocapitalize: "none",
    placeholder: "https://…",
    "aria-label": "Address",
  });
  baseField.value = saved.base_url ?? provider.baseUrl ?? "";
  const baseRow = el("div", {}, el("div", { class: "label" }, "Address"), baseField, el("p", { class: "hint" }, "Your provider's URL."));

  const suggestions = el("datalist", { id: `model-suggestions-${variant}` });
  const modelField = el("input", {
    class: "field mono",
    list: `model-suggestions-${variant}`,
    spellcheck: "false",
    autocapitalize: "none",
    "aria-label": "Model",
  });
  modelField.value = saved.model ?? provider.models[0] ?? "";

  // The wizard tucks the model name away: most people never change it.
  const modelName = el("code", {});
  const change = el("button", { type: "button", class: "link" }, "Change");
  const quiet = el("div", { class: "quiet" }, el("span", {}, "Model ", modelName), change);
  const modelRow = el(
    "div",
    {},
    el("div", { class: "label" }, "Model"),
    modelField,
    suggestions,
    el("p", { class: "hint" }, "Any model your provider offers. ", outLink(MODELS_DOC, "Learn more about models")),
  );
  change.addEventListener("click", () => {
    quiet.hidden = true;
    modelRow.hidden = false;
    modelField.focus();
  });
  modelField.addEventListener("input", () => {
    modelName.textContent = modelField.value.replace(/^[^/]+\//, "");
  });

  const render = () => {
    for (const { p, b } of segButtons) b.setAttribute("aria-checked", String(p.id === provider.id));
    suggestions.replaceChildren(...provider.models.map((m) => el("option", { value: m })));
    keyRow.hidden = provider.key === null;
    const hasSaved = saved.has_key && provider.id === savedFor;
    keySaved.hidden = !hasSaved || replacing;
    keyEntry.hidden = hasSaved && !replacing;
    keep.hidden = !hasSaved;
    keyField.placeholder = provider.key ?? "";
    keyHint.replaceChildren(
      provider.keyFrom ? `Get one at ${provider.keyFrom}. ` : "",
      "It stays on this Mac. ",
      variant === "wizard" ? outLink(MODELS_DOC, "What uses this?") : "",
    );
    baseRow.hidden = provider.baseUrl === undefined;
    modelName.textContent = modelField.value.replace(/^[^/]+\//, "") || "none";
  };
  render();

  const parts: (Node | null)[] = [el("div", {}, el("div", { class: "label" }, "Provider"), seg), keyRow, baseRow];
  if (variant === "wizard") {
    modelRow.hidden = true;
    parts.push(quiet, modelRow);
  } else {
    parts.push(modelRow, await modelStatus());
  }

  return {
    el: el("div", { class: "piece" }, ...parts),
    value: () => {
      const body: Record<string, string> = {
        model: modelField.value.trim(),
        base_url: provider.baseUrl === undefined ? "" : baseField.value.trim(),
      };
      // Left empty, the saved key stays: the page never had it to send back.
      // Unless the provider changed: the old key is the old provider's.
      if (provider.key !== null && typedKey) body.api_key = typedKey;
      else if (provider.key !== null && saved.has_key && provider.id !== savedFor) body.api_key = "";
      return body;
    },
    summary: () => {
      if (provider.key === null) return `${provider.name}, ${modelField.value.trim() || "no model"}`;
      if (typedKey) return `${provider.name}, key added`;
      if (saved.has_key && provider.id === savedFor) return `${provider.name}, key saved`;
      return `${provider.name}, no key yet`;
    },
  };
}

/** Whether the model is answering, from the health check. Filled in when it comes back. */
async function modelStatus(): Promise<HTMLElement> {
  const line = el("div", { class: "status-line" }, el("span", { class: "dot" }), "Checking the model…");
  void (async () => {
    try {
      const result = inApp ? await invoke<{ checks: Check[] }>("run_doctor") : { checks: PREVIEW_CHECKS };
      const check = result.checks.find((c) => c.name === "LLM connectivity");
      if (!check) {
        line.replaceChildren(el("span", { class: "dot" }), "Start Mycelium to check the model.");
        return;
      }
      const ok = check.status === "ok";
      line.className = ok ? "status-line ok" : "status-line bad";
      line.replaceChildren(
        el("span", { class: ok ? "dot on" : "dot bad" }),
        ok ? "Connected." : `Not connected: ${check.message}. ${check.details[check.details.length - 1] ?? ""}`,
      );
    } catch {
      line.replaceChildren(el("span", { class: "dot" }), "Couldn't check the model.");
    }
  })();
  return line;
}

/** The agent programs found on this Mac, and the folder they may start in. */
function agentsPiece(c: Choices, snap: Snapshot): HTMLElement {
  const agents = el("div", { class: "agents" }, el("span", { class: "hint" }, "Looking…"));
  const herdr = snap.herdr;
  const herdrPill = el(
    "span",
    { class: herdr.path ? "pill" : "pill missing" },
    el("span", { class: herdr.path ? "dot on" : "dot bad" }),
    herdr.bundled ? "herdr included" : herdr.path ? "herdr" : "herdr missing",
  );
  void (async () => {
    try {
      const found = inApp ? await invoke<{ frameworks?: Framework[] } | Framework[]>("scan_agents") : PREVIEW_AGENTS;
      const list = Array.isArray(found) ? found : (found.frameworks ?? []);
      const installed = list.filter((f) => f.installed);
      agents.replaceChildren(
        ...installed.map((f) =>
          el(
            "span",
            { class: "pill", title: f.launchable ? "" : "herdr can't start this one" },
            el("span", { class: f.launchable ? "dot on" : "dot" }),
            f.name,
            shortVersion(f.version) ? el("span", { class: "v" }, shortVersion(f.version)) : null,
          ),
        ),
        herdrPill,
      );
      if (installed.length === 0) {
        agents.append(el("span", { class: "hint" }, "No agent apps found. Install one, like Claude Code, to start agents from Mycelium."));
      }
    } catch (e) {
      agents.replaceChildren(herdrPill, el("span", { class: "hint" }, String(e)));
    }
  })();

  const rootPath = el("span", { class: "folder-path mono" }, c.root);
  const rootButton = el("button", { class: "button ghost", type: "button" }, "Choose…");
  rootButton.addEventListener("click", async () => {
    if (!inApp) return;
    const start = c.root.startsWith("~") ? snap.home + c.root.slice(1) : c.root;
    const picked = await invoke<string | null>("pick_folder", { start });
    if (picked) {
      c.root = tilde(picked, snap.home);
      rootPath.textContent = c.root;
    }
  });
  // Asked on first run only (``c.restore`` set); an existing install is asked
  // once, as a dialog, when the app starts.
  const restore =
    c.restore === undefined
      ? null
      : el(
          "div",
          { class: "share" },
          el(
            "label",
            { class: "share-label", for: "restore-agents" },
            checkbox("restore-agents", c.restore, (on) => (c.restore = on)),
            "Bring agents back after herdr restarts",
          ),
          el(
            "p",
            { class: "hint" },
            "Installs herdr's integration for each agent program here, which adds a hook to that program's own settings. With it, herdr reopens each agent in its own conversation.",
          ),
        );
  return el(
    "div",
    { class: "piece" },
    agents,
    el(
      "div",
      {},
      el("div", { class: "label" }, "Working folder"),
      el("div", { class: "folder" }, el("span", { class: "folder-icon", "aria-hidden": "true" }), rootPath, rootButton),
      el("p", { class: "hint" }, "Agents started from Mycelium can only work in this folder."),
    ),
    restore,
  );
}

/** Usage stats, off unless ticked, and only for a hub on this Mac. */
function privacyPiece(c: Choices): HTMLElement {
  return el(
    "div",
    { class: "share" },
    el(
      "label",
      { class: "share-label", for: "share-usage" },
      checkbox("share-usage", c.shareUsage, (on) => (c.shareUsage = on)),
      "Share anonymous usage stats",
    ),
    el(
      "p",
      { class: "hint" },
      "Only counts of tasks, flows and agents. Never names, rooms or messages. You can see them on the Metrics page.",
    ),
  );
}

/**
 * Ready-made rooms to explore, each added from a file the person was given.
 * The wizard offers them as an optional step; Settings lists what's here and
 * opens or removes it. Adding one points the hub at it, which it reads when it
 * next starts, so ``onChange`` is how the caller hears that a restart is due.
 */
function experiencesPiece(
  where: "wizard" | "settings",
  onChange: () => void,
): { el: HTMLElement; added: () => Experience[] } {
  let list: Experience[] = [];
  const error = el("p", { class: "error", role: "alert", hidden: "" });
  const box = el("div", { class: "experiences" }, el("span", { class: "hint" }, "Looking…"));

  const add = async (id: string) => {
    error.hidden = true;
    try {
      if (!inApp) {
        previewExperiences = previewExperiences.map((x) => (x.id === id ? { ...x, added: true, scenarios: 3 } : x));
        list = previewExperiences;
      } else {
        const now = await invoke<Experience[] | null>("add_experience", { id });
        if (!now) return; // they cancelled the picker
        list = now;
      }
      onChange();
      draw();
    } catch (e) {
      error.textContent = String(e);
      error.hidden = false;
    }
  };
  const remove = async (id: string) => {
    error.hidden = true;
    try {
      list = inApp ? await invoke<Experience[]>("remove_experience", { id }) : list.map((x) => (x.id === id ? { ...x, added: false, scenarios: 0 } : x));
      onChange();
      draw();
    } catch (e) {
      error.textContent = String(e);
      error.hidden = false;
    }
  };
  const textLink = (label: string, onClick: () => void) => {
    const b = el("button", { class: "link", type: "button" }, label);
    b.addEventListener("click", onClick);
    return b;
  };

  const draw = () => {
    box.replaceChildren(
      ...list.map((x) => {
        const count = `${x.scenarios} ${x.unit}${x.scenarios === 1 ? "" : "s"}`;
        const detail: (Node | string)[] =
          x.added && where === "settings"
            ? [
                `${count} · added from a file · `,
                textLink("Open", () => {
                  if (inApp) void invoke("open_experience", { path: x.open }).catch((e) => ((error.textContent = String(e)), (error.hidden = false)));
                }),
                " · ",
                textLink("Remove", () => void remove(x.id)),
              ]
            : x.added
              ? [`${count} · added from a file`]
              : [x.description];
        return el(
          "div",
          { class: x.added ? "exp on" : "exp" },
          el("i", { class: "check", "aria-hidden": "true" }),
          el("strong", {}, x.title),
          el("span", {}, ...detail),
        );
      }),
      // One experience today, so the one file is its content.
      ...(list[0] ? [textLink(list[0].added ? "Replace it from a file…" : "Add an experience from a file…", () => void add(list[0].id))] : []),
    );
  };

  void (async () => {
    try {
      list = inApp ? await invoke<Experience[]>("get_experiences") : previewExperiences;
      draw();
    } catch (e) {
      box.replaceChildren(el("span", { class: "hint" }, String(e)));
    }
  })();

  return {
    el: el("div", { class: "piece" }, box, error),
    added: () => list.filter((x) => x.added),
  };
}

const PROVIDER_NAMES: Record<string, string> = Object.fromEntries(PROVIDERS.map((p) => [p.id, p.name]));

/**
 * A Settings section for a team's hub: what the hub says it is set up with,
 * read-only. The settings live on the hub's machine; this only shows them.
 */
function hubReadOnly(at: "model" | "experiences" | "privacy", answer: Promise<HubSettings>): HTMLElement {
  const box = el("div", { class: "piece" }, el("span", { class: "hint" }, "Asking your team's hub…"));
  const row = (k: string, v: string) => [el("dt", {}, k), el("dd", {}, v)];
  void answer
    .then((s) => {
      let content: Node[];
      if (at === "model") {
        const m = s.model;
        content = [
          el("p", { class: "lede" }, "The model your team's hub runs its built-in agents with."),
          el(
            "dl",
            { class: "summary" },
            ...row("Provider", m.provider ? (PROVIDER_NAMES[m.provider] ?? m.provider) : "Not set"),
            ...row("Model", m.model ?? "Not set"),
            ...row("API key", m.has_key ? "Set" : "Not set"),
            ...(m.custom_endpoint ? row("Address", "Set on the hub") : []),
          ),
        ];
      } else if (at === "experiences") {
        content = [
          el("p", { class: "lede" }, "Example rooms your team's hub has."),
          ...(s.experiences.length === 0
            ? [el("p", { class: "hint" }, "None yet.")]
            : s.experiences.map((x) => {
                const open = el("button", { class: "link", type: "button" }, "Open");
                open.addEventListener("click", () => {
                  if (inApp) void invoke("open_experience", { path: x.open });
                });
                return el(
                  "div",
                  { class: "exp on" },
                  el("i", { class: "check", "aria-hidden": "true" }),
                  el("strong", {}, x.title),
                  el("span", {}, `${x.scenarios} ${x.unit}${x.scenarios === 1 ? "" : "s"} · on the hub · `, open),
                );
              })),
        ];
      } else {
        content = [
          el(
            "p",
            { class: "lede" },
            s.share_usage
              ? "Your team's hub shares anonymous usage stats: counts of tasks, flows and agents, never names, rooms or messages."
              : "Your team's hub doesn't share usage stats.",
          ),
        ];
      }
      box.replaceChildren(
        ...content,
        el("p", { class: "hint" }, "Set on your team's hub. To change it, change it there."),
      );
    })
    .catch((e) => {
      box.replaceChildren(el("p", { class: "lede" }, "Couldn't ask your team's hub."), el("p", { class: "hint" }, String(e)));
    });
  return box;
}

/** Everything Start changes on this Mac, said before anything happens. */
function setsUpPiece(c: Choices): HTMLElement {
  const items: [string, string][] = [
    ["mycelium and herdr on your PATH", "Links in ~/.local/bin, so agents can run them. A file you already have there is left alone."],
    ["~/.mycelium", "Your settings, and these choices. Rooms on this Mac keep their notes here too."],
    c.mode === "hub"
      ? ["Rooms on this Mac, while Mycelium is open", "SLIM, the hub and its UI, reachable only from this Mac (127.0.0.1)."]
      : ["The runner, while Mycelium is open", "It tells the hub which agents this Mac can start, and starts them in herdr."],
    ...(c.restore
      ? ([["herdr's integrations", "A hook in each agent program's own settings, so herdr can reopen its agents after a restart."]] as [string, string][])
      : []),
    ["Start at login", "Only if you turn it on, in Settings or from the menu bar icon."],
  ];
  return el(
    "details",
    { class: "sets-up-box" },
    el("summary", {}, "What this sets up on your Mac"),
    el("ul", { class: "sets-up" }, ...items.map(([what, why]) => el("li", {}, el("strong", {}, what), el("span", {}, why)))),
    el("p", { class: "hint" }, "No admin password, and nothing outside your home folder."),
  );
}

// ── first run: a short wizard ───────────────────────────────────────────────

type Step = "place" | "model" | "agents" | "experiences" | "ready";

async function wizard() {
  const snap = await snapshot();
  const c: Choices = { ...choicesFrom(snap), restore: true };
  let at: Step = "place";
  let skippedModel = false;
  // Built once, so what's typed survives going Back and forth.
  const model = await modelPiece("wizard");
  // Choosing where rooms live changes how many steps there are, so the bar
  // redraws on the spot.
  let redraw = () => {};
  const place = placePiece(c, () => redraw());
  const agents = agentsPiece(c, snap);
  // Nothing to restart yet: the hub that starts at the end reads what's added.
  const experiences = experiencesPiece("wizard", () => {});

  // An experience runs on rooms on this Mac, so a team's hub skips it.
  const steps = (): Step[] =>
    c.mode === "hub" ? ["place", "model", "agents", "experiences", "ready"] : ["place", "agents", "ready"];

  const show = () => {
    const order = steps();
    const i = order.indexOf(at);
    const error = el("p", { class: "error", role: "alert", hidden: "" });
    const fail = (msg: string) => {
      error.textContent = msg;
      error.hidden = false;
    };

    let title: string;
    let lede: string | null = null;
    let body: Node;
    if (at === "place") {
      title = "Rooms where you and your agents work together";
      lede = "First, where should your rooms live?";
      body = place.el;
    } else if (at === "model") {
      title = "Give Mycelium's own agents a model";
      lede =
        "Mycelium comes with agents of its own: one helps your agents agree, others play a role in a scenario, another keeps notes. They need a model to think with. Agents you bring, like Claude Code, sign in on their own.";
      body = model.el;
    } else if (at === "agents") {
      title = "Agents on this Mac";
      lede = "Mycelium can start these for you and bring them into a room.";
      body = agents;
    } else if (at === "experiences") {
      title = "Add an experience";
      lede = "Ready-made rooms to explore. Optional, and you can add them later.";
      body = experiences.el;
    } else {
      title = "Ready to start";
      const summary: [string, string][] = [
        ["Rooms", c.mode === "hub" ? "On this Mac, reachable only from it" : `On ${c.hubUrl.trim()}`],
      ];
      if (c.mode === "hub") summary.push(["Model", skippedModel ? "Not set yet. Add one in Settings (⌘,)." : model.summary()]);
      summary.push(["Agents work in", c.root]);
      const added = c.mode === "hub" ? experiences.added() : [];
      if (added.length > 0) summary.push(["Added", added.map((x) => x.title).join(", ")]);
      body = el(
        "div",
        { class: "piece" },
        el("dl", { class: "summary" }, ...summary.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
        c.mode === "hub" ? privacyPiece(c) : null,
        setsUpPiece(c),
      );
    }

    const back = i > 0 ? el("button", { class: "button ghost", type: "button" }, "Back") : null;
    back?.addEventListener("click", () => {
      at = order[i - 1];
      show();
    });
    const skip =
      at === "model" || at === "experiences"
        ? el("button", { class: "button text", type: "button" }, at === "model" ? "Skip for now" : "Skip")
        : null;
    skip?.addEventListener("click", () => {
      if (at === "model") skippedModel = true;
      at = order[i + 1];
      show();
    });
    const last = at === "ready";
    const next = el("button", { class: "button", type: "button" }, last ? (c.mode === "hub" ? "Start Mycelium" : "Connect") : "Continue");
    next.addEventListener("click", async () => {
      if (at === "place") {
        const problem = place.problem();
        if (problem) return fail(problem);
      }
      if (at === "model") skippedModel = false;
      if (!last) {
        at = steps()[steps().indexOf(at) + 1];
        return show();
      }
      next.disabled = true;
      try {
        await startWith(c, skippedModel ? null : model.value());
      } catch (e) {
        fail(String(e));
        next.disabled = false;
      }
    });

    app.replaceChildren(
      el(
        "section",
        { class: "card" },
        el("div", { class: "steps", "aria-label": `Step ${i + 1} of ${order.length}` }, ...order.map((_, n) => el("span", { class: n < i ? "done" : n === i ? "on" : "" }))),
        el(
          "div",
          { class: "card-body" },
          at === "place" ? el("div", { class: "brand" }, el("img", { class: "brand-mark", src: "/mark.png", alt: "" }), "Mycelium") : null,
          el("div", {}, el("h1", { class: "title" }, title), lede ? el("p", { class: "lede" }, lede) : null),
          body,
          error,
        ),
        el(
          "div",
          { class: "card-foot" },
          back,
          el("div", { class: "where" }, at === "place" ? "You can change any of this later in Settings." : ""),
          el("div", { class: "actions" }, skip, next),
        ),
      ),
    );
  };
  redraw = show;
  show();
}

// ── Settings: the same pieces, one section at a time ─────────────────────────

type Section = "mac" | "model" | "agents" | "experiences" | "privacy";

async function settingsWindow(open: Section = "mac") {
  const snap = await snapshot();
  const c = choicesFrom(snap);
  // The same sections whatever is chosen: one that doesn't apply says why,
  // rather than leaving the sidebar.
  const sections = (): [Section, string][] => [
    ["mac", "This Mac"],
    ["model", "Model"],
    ["agents", "Agents"],
    ["experiences", "Experiences"],
    ["privacy", "Privacy"],
  ];
  let at: Section = sections().some(([s]) => s === open) ? open : "mac";
  // On a team's hub these are set there; asked once per window, and shown as is.
  const hubSettings: Promise<HubSettings> | null =
    c.mode === "client" ? (inApp ? invoke<HubSettings>("get_hub_settings") : Promise.resolve(PREVIEW_HUB)) : null;

  const show = async () => {
    const error = el("p", { class: "error", role: "alert", hidden: "" });
    let save: () => Promise<void> = () => startWith(c, null);
    let note = "Mycelium will restart after saving.";
    // A section with nothing to set on this Mac offers nothing to save.
    let nothingToSave = false;
    // A section whose changes happen as they're made saves only once there is one.
    let waitForChange = false;
    const saveButton = el("button", { class: "button", type: "button" }, "Save");
    let body: Node;
    if (at === "mac") {
      const place = placePiece(c, () => void 0);
      const autostart = el("label", { class: "share-label", for: "autostart" }, checkbox("autostart", false, (on) => {
        if (inApp) void invoke<boolean>("set_autostart", { on });
      }), "Start Mycelium when I log in");
      if (inApp) void invoke<boolean>("get_autostart").then((on) => ((autostart.querySelector("input") as HTMLInputElement).checked = on));
      body = el(
        "div",
        { class: "piece" },
        place.el,
        el("div", { class: "share" }, autostart, el("p", { class: "hint" }, "Changes right away.")),
      );
      save = async () => {
        const problem = place.problem();
        if (problem) throw new Error(problem);
        await startWith(c, null);
      };
    } else if ((at === "model" || at === "experiences" || at === "privacy") && hubSettings) {
      body = hubReadOnly(at, hubSettings);
      nothingToSave = true;
    } else if (at === "model") {
      const model = await modelPiece("settings");
      body = el("div", { class: "piece" }, el("p", { class: "lede" }, "The model Mycelium's built-in agents use. Agents like Claude Code use their own accounts."), model.el);
      save = () => startWith(c, model.value());
    } else if (at === "agents") {
      body = agentsPiece(c, snap);
    } else if (at === "experiences") {
      // Added or removed already; the hub reads it when it starts again.
      let changed = false;
      const experiences = experiencesPiece("settings", () => {
        changed = true;
        saveButton.disabled = false;
      });
      body = el("div", { class: "piece" }, el("p", { class: "lede" }, "Example rooms you can try."), experiences.el);
      save = async () => {
        if (changed) await startWith(c, null);
      };
      waitForChange = true;
    } else {
      body = privacyPiece(c);
    }

    const nav = el(
      "nav",
      { class: "nav", "aria-label": "Settings" },
      ...sections().map(([s, label]) => {
        const b = el("button", { type: "button", class: s === at ? "on" : "", "aria-current": s === at ? "page" : "false" }, label);
        b.addEventListener("click", () => {
          at = s;
          void show();
        });
        return b;
      }),
    );
    const cancel = el("button", { class: "button ghost", type: "button" }, "Cancel");
    cancel.addEventListener("click", async () => {
      if (!inApp) return;
      try {
        await invoke("open_room");
      } catch {
        // Not up yet (or stopped): show how starting is going instead.
        await loading();
      }
    });
    saveButton.hidden = nothingToSave;
    saveButton.disabled = waitForChange;
    if (nothingToSave) note = "";
    saveButton.addEventListener("click", async () => {
      saveButton.disabled = true;
      error.hidden = true;
      try {
        await save();
      } catch (e) {
        error.textContent = e instanceof Error ? e.message : String(e);
        error.hidden = false;
        saveButton.disabled = false;
      }
    });

    app.replaceChildren(
      el(
        "section",
        { class: "card wide" },
        el(
          "div",
          { class: "settings" },
          nav,
          el(
            "div",
            { class: "pane" },
            el("h2", { class: "pane-title" }, sections().find(([s]) => s === at)?.[1] ?? ""),
            body,
            error,
          ),
        ),
        el("div", { class: "card-foot" }, el("div", { class: "where" }, note), el("div", { class: "actions" }, cancel, saveButton)),
      ),
    );
  };
  await show();
}

// ── starting ────────────────────────────────────────────────────────────────

const LABELS: Record<string, string> = {
  herdr: "herdr",
  slim: "SLIM node",
  hub: "Hub",
  ui: "Room UI",
  runner: "Runner",
};
const SAID: Record<State, string> = {
  starting: "starting",
  running: "running",
  stopped: "stopped",
  failed: "failed",
  disabled: "",
  waiting: "waiting for you",
};

/** Whether `version` is older than `than`, by its numbers (unknown is not older). */
function olderThan(version: string | null, than: string): boolean {
  const nums = (v: string) => (v.match(/\d+(?:\.\d+)+/)?.[0] ?? "").split(".").filter(Boolean).map(Number);
  const [a, b] = [nums(version ?? ""), nums(than)];
  if (!a.length || !b.length || than.includes("dev")) return false;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0);
  }
  return false;
}

/**
 * A hub already on the app's port that the app didn't start, put to the
 * person: whose it is, its version, where it keeps its data, and the choice.
 */
function hubQuestion(q: HubQuestion, home: string, answered: (e: unknown) => void): HTMLElement {
  const h = q.hub;
  const tag = (text: string) => el("span", { class: "tag warn" }, text);
  const row = (label: string, ...value: (Node | string | null)[]) =>
    el("div", { class: "facts-row" }, el("dt", {}, label), el("dd", {}, ...value));

  const startedBy =
    h.source === "docker"
      ? h.project
        ? `Docker, project ${h.project}`
        : `Docker, container ${h.container ?? "unknown"}`
      : h.source === "process"
        ? `A process on this Mac (${h.pid})`
        : "Something Mycelium can't identify";
  const older = h.version && !h.dev_build && olderThan(h.version, q.app_version);
  const data = h.data_path ? tilde(h.data_path, home) : "unknown";
  const elsewhere = q.same_store === false;
  const stops =
    h.source === "docker" && h.project
      ? `Starting Mycelium's own stops the Docker project ${h.project} first. Its data stays where it is.`
      : h.source === "process"
        ? `Starting Mycelium's own stops process ${h.pid} first. Its data stays where it is.`
        : "Starting Mycelium's own stops it first. Its data stays where it is.";

  const use = el("button", { class: "button ghost", type: "button" }, "Use it");
  const replace = el("button", { class: "button", type: "button" }, "Start Mycelium's own");
  const pick = (choice: "use" | "stop") => {
    use.disabled = replace.disabled = true;
    if (inApp) void invoke("answer_existing_hub", { choice }).catch((e) => ((use.disabled = replace.disabled = false), answered(e)));
  };
  use.addEventListener("click", () => pick("use"));
  replace.addEventListener("click", () => pick("stop"));

  return el(
    "div",
    { class: "hub-ask", role: "alertdialog", "aria-labelledby": "hub-ask-title" },
    el("h2", { id: "hub-ask-title" }, `Another hub is already on port ${h.port ?? 8000}`),
    el("p", { class: "hub-ask-lede" }, "Mycelium didn't start it, so it's checking with you before using it."),
    el(
      "dl",
      { class: "facts" },
      row("Started by", startedBy),
      h.image ? row("Image", el("code", {}, h.image), h.dev_build ? tag("dev build") : null) : null,
      row("Version", h.version ?? "unknown", older ? tag(`older than ${q.app_version}`) : null),
      row("Data", el("code", {}, data), elsewhere ? tag("not your data folder") : null),
    ),
    elsewhere
      ? el(
          "p",
          { class: "hub-ask-note" },
          "If you use it, your rooms and memories are read from and saved to ",
          el("code", {}, data),
          ", not ",
          el("code", {}, tilde(q.data_dir, home)),
          ".",
        )
      : null,
    el("div", { class: "hub-ask-foot" }, el("p", { class: "hint" }, stops), el("div", { class: "actions" }, use, replace)),
  );
}

async function loading(setup: PathSetup | null = null) {
  const snap = await snapshot();
  const mode = snap.settings?.mode ?? "hub";
  const names = mode === "hub" ? ["herdr", "slim", "hub", "ui", "runner"] : ["herdr", "runner"];
  const rows = new Map<string, { dot: HTMLElement; state: HTMLElement; detail: HTMLElement }>();
  const list = el("ul", { class: "status-list" });
  for (const name of names) {
    const dot = el("span", { class: "dot" });
    const state = el("span", { class: "state" }, "waiting");
    // Why a part is starting over or has stopped, in its own words.
    const detail = el("div", { class: "status-detail", hidden: "" });
    rows.set(name, { dot, state, detail });
    list.append(el("li", {}, el("div", { class: "status-row" }, dot, LABELS[name] ?? name, state), detail));
  }
  const error = el("p", { class: "error", role: "alert", hidden: "" });
  const log = el("div", { class: "log" });
  // A hub the app didn't start, and anything else about the hubs on this Mac.
  const ask = el("div", { hidden: "" });
  const warned = el("div", { class: "note", hidden: "" });
  const change = el("button", { class: "button ghost", type: "button" }, "Settings");
  change.addEventListener("click", () => void settingsWindow());
  const showLog = el("button", { class: "button ghost", type: "button" }, "Show log");
  showLog.addEventListener("click", () => {
    if (inApp) void invoke("open_log").catch((e) => ((error.textContent = String(e)), (error.hidden = false)));
  });

  const pathNote =
    setup && !setup.onPath && setup.linked.length > 0
      ? el(
          "div",
          { class: "note" },
          "Mycelium put ",
          el("code", {}, "mycelium"),
          " and ",
          el("code", {}, "herdr"),
          " in ~/.local/bin, which your shell doesn't search yet. Add this line to your shell profile so your own terminals find them too: ",
          el("code", {}, setup.line),
        )
      : null;
  const skipped =
    setup && setup.skipped.length > 0
      ? el("p", { class: "hint" }, `Kept your own ${setup.skipped.join(" and ")} in ~/.local/bin.`)
      : null;

  const apply = (status: Status | null) => {
    for (const [name, row] of rows) {
      const c = status?.components?.[name];
      const s = c?.state;
      row.dot.className = s === "running" ? "dot on" : s === "failed" ? "dot bad" : "dot";
      row.state.textContent = s ? SAID[s] || "" : "waiting";
      const why = s !== "running" ? (c?.detail ?? "") : "";
      row.detail.textContent = why;
      row.detail.hidden = !why;
      row.detail.classList.toggle("bad", s === "failed");
    }
    const q = status?.question ?? null;
    const asked = q ? `${q.hub.description}|${q.same_store}` : "";
    if (ask.dataset.asked !== asked) {
      ask.dataset.asked = asked;
      ask.replaceChildren(
        ...(q ? [hubQuestion(q, snap.home, (e) => ((error.textContent = String(e)), (error.hidden = false)))] : []),
      );
      ask.hidden = !q;
    }
    const said = q ? [] : (status?.warnings ?? []);
    warned.replaceChildren(...said.map((w) => el("div", {}, w)));
    warned.hidden = said.length === 0;
  };
  apply(snap.status);
  if (snap.lastError) {
    error.textContent = snap.lastError;
    error.hidden = false;
  }

  const where = mode === "hub" ? "Starting on this Mac" : `Connecting to ${snap.settings?.hubUrl ?? "the hub"}`;
  app.replaceChildren(
    el(
      "section",
      { class: "card" },
      head(where),
      el("div", { class: "card-body" }, pathNote, skipped, ask, warned, list, error, log),
      el(
        "div",
        { class: "card-foot" },
        el("div", { class: "where" }, "The room opens here once it's ready."),
        el("div", { class: "actions" }, showLog, change),
      ),
    ),
  );

  if (!inApp) return;
  await listen<Status>("status", (e) => {
    error.hidden = true;
    apply(e.payload);
  });
  await listen<{ message: string }>("supervisor-error", (e) => {
    error.textContent = e.payload.message;
    error.hidden = false;
  });
  await listen<{ component: string; line: string }>("log", (e) => {
    log.textContent = `${e.payload.component}: ${e.payload.line}`;
  });
}

// ── health check ────────────────────────────────────────────────────────────

const MARK: Record<string, { glyph: string; cls: string }> = {
  ok: { glyph: "✓", cls: "ok" },
  warning: { glyph: "!", cls: "warn" },
  info: { glyph: "i", cls: "info" },
};

async function doctor() {
  const body = el("div", { class: "card-body" }, el("p", { class: "hint" }, "Checking…"));
  const verdict = el("div", { class: "where" });
  const again = el("button", { class: "button ghost", type: "button" }, "Check again");
  const showLog = el("button", { class: "button ghost", type: "button" }, "Show log");
  showLog.addEventListener("click", () => {
    if (inApp) void invoke("open_log").catch((e) => (verdict.textContent = String(e)));
  });
  const back = el("button", { class: "button", type: "button" }, "Back to Mycelium");
  back.addEventListener("click", async () => {
    try {
      if (inApp) await invoke("open_room");
    } catch (e) {
      verdict.textContent = String(e);
    }
  });

  const run = async () => {
    again.disabled = true;
    body.replaceChildren(el("p", { class: "hint" }, "Checking…"));
    verdict.textContent = "";
    try {
      const result = inApp ? await invoke<{ checks: Check[] }>("run_doctor") : { checks: PREVIEW_CHECKS };
      const sections = new Map<string, Check[]>();
      for (const c of result.checks) sections.set(c.section, [...(sections.get(c.section) ?? []), c]);
      body.replaceChildren(
        ...[...sections].map(([title, checks]) =>
          el(
            "div",
            {},
            el("div", { class: "label" }, title),
            el(
              "ul",
              { class: "checks" },
              ...checks.map((c) => {
                const mark = MARK[c.status] ?? { glyph: "✗", cls: "bad" };
                return el(
                  "li",
                  {},
                  el("span", { class: `check-mark ${mark.cls}`, "aria-label": c.status }, mark.glyph),
                  el(
                    "div",
                    { class: "check-text" },
                    el("div", {}, el("strong", {}, c.name), " ", el("span", { class: "check-message" }, c.message)),
                    ...c.details.map((d) => el("div", { class: "check-detail" }, d)),
                  ),
                );
              }),
            ),
          ),
        ),
      );
      const problems = result.checks.filter((c) => !["ok", "info"].includes(c.status)).length;
      verdict.textContent = problems ? `${problems} thing${problems === 1 ? "" : "s"} to look at` : "Everything checks out";
    } catch (e) {
      body.replaceChildren(el("p", { class: "error" }, String(e)));
    } finally {
      again.disabled = false;
    }
  };
  again.addEventListener("click", () => void run());

  app.replaceChildren(
    el(
      "section",
      { class: "card" },
      head("Health check. Each part Mycelium runs on this Mac, and whether it's working."),
      body,
      el("div", { class: "card-foot" }, verdict, el("div", { class: "actions" }, showLog, again, back)),
    ),
  );
  await run();
}

async function boot() {
  const params = new URLSearchParams(location.search);
  const view = params.get("view");
  if (view === "doctor") return doctor();
  const snap = await snapshot();
  // The menu's Settings… opens view=onboarding: the wizard until the first
  // run is done, Settings after.
  if (!snap.settings) return wizard();
  if (view === "onboarding" || view === "settings") return settingsWindow((params.get("section") as Section) || "mac");
  await loading();
}

void boot();
