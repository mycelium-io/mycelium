// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The app's own screens: the first-run wizard, Settings, the wait while
// Mycelium starts, and the health check. Once the supervisor says the room UI
// is up, the app points this window at it and these pages are gone.

import "./style.css";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Mode = "hub" | "client";
type State = "starting" | "running" | "stopped" | "failed" | "disabled";

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

interface Status {
  type: "status";
  mode: Mode;
  ui_url?: string;
  api_url?: string;
  components: Record<string, { state: State; detail?: string | null }>;
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
const MODELS_DOC = "https://mycelium-io.github.io/mycelium/reference.html#models";

function providerOf(model: string | null): Provider {
  const prefix = (model ?? "").split("/")[0];
  return PROVIDERS.find((p) => p.id === prefix) ?? (model ? PROVIDERS[PROVIDERS.length - 1] : PROVIDERS[0]);
}

const inApp = "__TAURI_INTERNALS__" in window;
const app = document.getElementById("app")!;

// ── outside the app (a browser preview): a made-up machine so pages still draw ──

const previewSetUp = new URLSearchParams(location.search).get("preview") === "settings";
const PREVIEW: Snapshot = {
  settings: previewSetUp ? { mode: "hub", hubUrl: null, roots: ["/Users/you/code"], shareUsage: false } : null,
  status: null,
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
  await loading(setup);
}

// ── the pieces: each written once, shown by the wizard a step at a time and
// by Settings a section at a time ─────────────────────────────────────────────

/** Where rooms live: on this Mac, or on a team's hub at an address. */
function placePiece(c: Choices, onChange: () => void): { el: HTMLElement; problem: () => string | null } {
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
    onChange();
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
      c.mode = value;
      render();
      onChange();
    });
    return b;
  };
  const here = choice("hub", "On this Mac", "Your rooms, notes and agents, all here. Best for trying it out or giving a demo.");
  const team = choice("client", "On my team's hub", "Join rooms someone else runs. You'll need its address.");
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
  const keyRow = el("div", {}, el("div", { class: "label" }, "API key"), keyField, keyHint);

  const baseField = el("input", {
    class: "field mono",
    spellcheck: "false",
    autocapitalize: "none",
    placeholder: "https://…",
    "aria-label": "Address",
  });
  baseField.value = saved.base_url ?? provider.baseUrl ?? "";
  const baseRow = el("div", {}, el("div", { class: "label" }, "Address"), baseField, el("p", { class: "hint" }, "Where the model answers."));

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
    const kept = saved.key_hint ? `Saved key ending ${saved.key_hint}` : "A key is saved";
    keyField.placeholder = saved.has_key ? `${kept}. Paste a new one to replace it.` : (provider.key ?? "");
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
      if (provider.key !== null && typedKey) body.api_key = typedKey;
      return body;
    },
    summary: () => {
      if (provider.key === null) return `${provider.name}, ${modelField.value.trim() || "no model"}`;
      if (typedKey) return `${provider.name}, key ending ${typedKey.slice(-4)}`;
      if (saved.has_key) return `${provider.name}, key ending ${saved.key_hint ?? "…"}`;
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
        ok ? "Working: the model answered." : `Not working: ${check.message}. ${check.details[check.details.length - 1] ?? ""}`,
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
        agents.append(el("span", { class: "hint" }, "No agent programs found yet. Install one, like Claude Code, to start agents from Mycelium."));
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
  return el(
    "div",
    { class: "piece" },
    agents,
    el(
      "div",
      {},
      el("div", { class: "label" }, "Where they work"),
      el("div", { class: "folder" }, el("span", { class: "folder-icon", "aria-hidden": "true" }), rootPath, rootButton),
      el("p", { class: "hint" }, "Agents you start from Mycelium only work inside this folder."),
    ),
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
      "Counts of tasks, flows and agents, so we know what's working. Never names, rooms or what anyone wrote. You can see them on the Metrics page either way.",
    ),
  );
}

/** Everything Start changes on this Mac, said before anything happens. */
function setsUpPiece(c: Choices): HTMLElement {
  const items: [string, string][] = [
    ["mycelium and herdr on your PATH", "Links in ~/.local/bin, so agents can run them. A file you already have there is left alone."],
    ["~/.mycelium", "Your settings, and these choices. Rooms on this Mac keep their notes here too."],
    c.mode === "hub"
      ? ["Rooms on this Mac, while Mycelium is open", "SLIM, the hub and its UI, reachable only from this Mac (127.0.0.1)."]
      : ["The runner, while Mycelium is open", "It tells the hub which agents this Mac can start, and starts them in herdr."],
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

type Step = "place" | "model" | "agents" | "ready";

async function wizard() {
  const snap = await snapshot();
  const c = choicesFrom(snap);
  let at: Step = "place";
  let skippedModel = false;
  // Built once, so what's typed survives going Back and forth.
  const model = await modelPiece("wizard");
  const place = placePiece(c, () => void 0);
  const agents = agentsPiece(c, snap);

  const steps = (): Step[] => (c.mode === "hub" ? ["place", "model", "agents", "ready"] : ["place", "agents", "ready"]);

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
    } else {
      title = "Ready to start";
      const summary: [string, string][] = [
        ["Rooms", c.mode === "hub" ? "On this Mac, reachable only from it" : `On ${c.hubUrl.trim()}`],
      ];
      if (c.mode === "hub") summary.push(["Model", skippedModel ? "Not set yet. Add one in Settings (⌘,)." : model.summary()]);
      summary.push(["Agents work in", c.root]);
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
    const skip = at === "model" ? el("button", { class: "button text", type: "button" }, "Skip for now") : null;
    skip?.addEventListener("click", () => {
      skippedModel = true;
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
  show();
}

// ── Settings: the same pieces, one section at a time ─────────────────────────

type Section = "mac" | "model" | "agents" | "privacy";

async function settingsWindow(open: Section = "mac") {
  const snap = await snapshot();
  const c = choicesFrom(snap);
  const sections = (): [Section, string][] =>
    c.mode === "hub"
      ? [["mac", "This Mac"], ["model", "Model"], ["agents", "Agents"], ["privacy", "Privacy"]]
      : [["mac", "This Mac"], ["agents", "Agents"]];
  let at: Section = sections().some(([s]) => s === open) ? open : "mac";

  const show = async () => {
    const error = el("p", { class: "error", role: "alert", hidden: "" });
    let save: () => Promise<void> = () => startWith(c, null);
    let note = "Saving restarts Mycelium.";
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
        el("div", { class: "share" }, autostart, el("p", { class: "hint" }, "Applies right away, without saving.")),
      );
      save = async () => {
        const problem = place.problem();
        if (problem) throw new Error(problem);
        await startWith(c, null);
      };
    } else if (at === "model") {
      const model = await modelPiece("settings");
      body = el("div", { class: "piece" }, el("p", { class: "lede" }, "What Mycelium's own agents think with. Agents you bring sign in on their own."), model.el);
      save = () => startWith(c, model.value());
      note = "Saving restarts Mycelium's own agents.";
    } else if (at === "agents") {
      body = agentsPiece(c, snap);
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
    const saveButton = el("button", { class: "button", type: "button" }, "Save");
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
};

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
      el("div", { class: "card-body" }, pathNote, skipped, list, error, log),
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
