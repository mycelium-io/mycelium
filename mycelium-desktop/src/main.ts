// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The app's own screen: the first-run choice, and the wait while Mycelium
// starts. Once the supervisor says the room UI is up, the app points this
// window at it and this page is gone.

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

type ProviderId = "anthropic" | "openai" | "openrouter" | "ollama" | "custom";

interface Provider {
  id: ProviderId;
  name: string;
  /** Suggestions, the first the default; the same ones `mycelium install` offers. */
  models: string[];
  /** The key field's placeholder; null for a provider that needs no key. */
  key: string | null;
  /** Where it answers, for a provider the hub can't find on its own. */
  baseUrl?: string;
}

const PROVIDERS: Provider[] = [
  {
    id: "anthropic",
    name: "Anthropic",
    models: ["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-6", "anthropic/claude-haiku-4-5"],
    key: "sk-ant-…",
  },
  { id: "openai", name: "OpenAI", models: ["openai/gpt-4.1", "openai/gpt-4o", "openai/gpt-4o-mini", "openai/o3"], key: "sk-…" },
  { id: "openrouter", name: "OpenRouter", models: ["openrouter/anthropic/claude-sonnet-4-6"], key: "sk-or-…" },
  {
    id: "ollama",
    name: "Ollama",
    models: ["ollama/llama3.3", "ollama/mistral", "ollama/qwen2.5"],
    key: null,
    baseUrl: "http://localhost:11434",
  },
  { id: "custom", name: "Other", models: [], key: "API key, if it needs one", baseUrl: "" },
];

function providerOf(model: string | null): Provider {
  const prefix = (model ?? "").split("/")[0];
  return PROVIDERS.find((p) => p.id === prefix) ?? (model ? PROVIDERS[PROVIDERS.length - 1] : PROVIDERS[0]);
}

const PREVIEW_MODEL: ModelView = { model: null, base_url: null, has_key: false, key_hint: null };

const inApp = "__TAURI_INTERNALS__" in window;
const app = document.getElementById("app")!;

/** Outside the app (a browser preview), a made-up machine so the page still draws. */
const PREVIEW: Snapshot = {
  settings: null,
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

async function snapshot(): Promise<Snapshot> {
  return inApp ? invoke<Snapshot>("get_state") : PREVIEW;
}

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

function head(sub: string): HTMLElement {
  return el(
    "div",
    { class: "card-head" },
    el("div", { class: "brand" }, el("img", { class: "brand-mark", src: "/mark.png", alt: "" }), "Mycelium"),
    el("p", { class: "sub" }, sub),
  );
}

// ── the model ───────────────────────────────────────────────────────────────

/**
 * The model the hub's own agents (personas, the aligner) think with: a
 * provider, a model, a key, and an address for one the hub can't find on its
 * own. The saved key is never shown, only its last four characters; leaving
 * the key field empty keeps it.
 */
async function modelSection(): Promise<{ section: HTMLElement; value: () => Record<string, string> }> {
  let saved = PREVIEW_MODEL;
  try {
    if (inApp) saved = await invoke<ModelView>("get_model");
  } catch {
    // Unread settings start from the defaults; saving still writes them.
  }
  let provider = providerOf(saved.model);

  const providerField = el("select", { class: "field", "aria-label": "Provider" });
  for (const p of PROVIDERS) {
    const option = el("option", { value: p.id }, p.name);
    if (p.id === provider.id) option.setAttribute("selected", "");
    providerField.append(option);
  }
  const suggestions = el("datalist", { id: "model-suggestions" });
  const modelField = el("input", {
    class: "field mono",
    list: "model-suggestions",
    spellcheck: "false",
    autocapitalize: "none",
    "aria-label": "Model",
  });
  modelField.value = saved.model ?? provider.models[0] ?? "";
  const keyField = el("input", {
    class: "field mono",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    "aria-label": "API key",
  });
  const baseField = el("input", {
    class: "field mono",
    spellcheck: "false",
    autocapitalize: "none",
    placeholder: "https://…",
    "aria-label": "Address",
  });
  baseField.value = saved.base_url ?? provider.baseUrl ?? "";
  const keyRow = el("div", {}, keyField);
  const baseRow = el("div", {}, baseField);

  const render = () => {
    suggestions.replaceChildren(...provider.models.map((m) => el("option", { value: m })));
    keyRow.hidden = provider.key === null;
    const ask =
      provider.id === "custom" ? "Paste the API key, if it needs one" : `Paste your ${provider.name} API key (${provider.key})`;
    const kept = saved.key_hint ? `Saved key ending ${saved.key_hint}` : "A key is saved";
    keyField.placeholder = saved.has_key ? `${kept}. Paste a new one to replace it.` : ask;
    baseRow.hidden = provider.baseUrl === undefined;
  };
  providerField.addEventListener("change", () => {
    provider = PROVIDERS.find((p) => p.id === providerField.value) ?? PROVIDERS[0];
    modelField.value = provider.models[0] ?? "";
    baseField.value = provider.baseUrl ?? "";
    render();
  });
  render();

  const section = el(
    "div",
    {},
    el("div", { class: "label" }, "Model"),
    el("div", { class: "model-row" }, providerField, modelField, suggestions),
    keyRow,
    baseRow,
    el(
      "p",
      { class: "hint" },
      "What the agents this hub runs, like personas and the aligner, think with. Agents you bring, like Claude Code, use their own login.",
    ),
  );
  keyRow.style.marginTop = "8px";
  baseRow.style.marginTop = "8px";

  return {
    section,
    value: () => {
      const body: Record<string, string> = {
        model: modelField.value.trim(),
        base_url: provider.baseUrl === undefined ? "" : baseField.value.trim(),
      };
      // Left empty, the saved key stays: the page never had it to send back.
      if (provider.key !== null && keyField.value.trim()) body.api_key = keyField.value.trim();
      return body;
    },
  };
}

// ── first run, and Settings ─────────────────────────────────────────────────

async function onboarding() {
  const snap = await snapshot();
  // The same page is the first run and, after it, Settings.
  const firstRun = !snap.settings;
  let mode: Mode = snap.settings?.mode ?? "hub";
  let hubUrl = snap.settings?.hubUrl ?? "";
  let root = tilde(snap.settings?.roots[0] ?? snap.home, snap.home);
  let shareUsage = snap.settings?.shareUsage ?? false;

  const error = el("p", { class: "error", role: "alert", hidden: "" });
  // Asked here, where a Mac's hub starts, and nowhere else: off unless ticked.
  // Only for a hub on this Mac; in client mode the hub is someone else's.
  const shareBox = el("input", { type: "checkbox", class: "toggle", id: "share-usage" });
  shareBox.checked = shareUsage;
  shareBox.addEventListener("change", () => {
    shareUsage = shareBox.checked;
  });
  const shareRow = el(
    "div",
    { class: "share" },
    el("label", { class: "share-label", for: "share-usage" }, shareBox, "Share anonymous usage stats"),
    el(
      "p",
      { class: "hint" },
      "Counts of tasks, flows and agents, so we know what's working. Never names, rooms or what anyone wrote. You can see them on the Metrics page either way.",
    ),
  );
  const model = await modelSection();
  const hubField = el("input", {
    class: "field mono",
    placeholder: "https://hub.example.com",
    spellcheck: "false",
    autocapitalize: "none",
    "aria-label": "Hub address",
  });
  hubField.value = hubUrl;
  const hubRow = el("div", {}, hubField);
  const rootPath = el("span", { class: "folder-path mono", title: "" }, root);
  const rootButton = el("button", { class: "button ghost", type: "button" }, "Choose…");
  const rootField = el("div", { class: "folder" }, el("span", { class: "folder-icon", "aria-hidden": "true" }), rootPath, rootButton);
  const button = el("button", { class: "button", type: "button" });
  const where = el("div", { class: "where" });
  // Said before anything happens: everything Start changes on this Mac.
  const setsUpList = el("ul", { class: "sets-up" });
  const setsUp = el(
    "details",
    { class: "sets-up-box" },
    el("summary", {}, "What this sets up on your Mac"),
    setsUpList,
    el("p", { class: "hint" }, "No admin password, and nothing outside your home folder."),
  );
  const renderSetsUp = () => {
    const items: [string, string][] = [
      ["mycelium and herdr on your PATH", "Links in ~/.local/bin, so agents can run them. A file you already have there is left alone."],
      ["~/.mycelium", "Your settings, and this choice. Running a hub keeps your rooms and memories here too."],
      mode === "hub"
        ? ["A hub on this Mac, while Mycelium is open", "SLIM, the hub and its UI, reachable only from this Mac (127.0.0.1)."]
        : ["The runner, while Mycelium is open", "It tells the hub which agents this Mac can start, and starts them in herdr."],
      ["Start at login", "Only if you turn it on, from the menu bar icon."],
    ];
    setsUpList.replaceChildren(
      ...items.map(([what, why]) => el("li", {}, el("strong", {}, what), el("span", {}, why))),
    );
  };

  const choice = (value: Mode, title: string, sub: string) => {
    const b = el("button", { class: "choice", type: "button", role: "radio" }, el("strong", {}, title), el("span", {}, sub));
    b.addEventListener("click", () => {
      mode = value;
      render();
    });
    return b;
  };
  const hubChoice = choice("hub", "Run a hub on this Mac", "Rooms, memory and agents, all here");
  const clientChoice = choice("client", "Connect to a hub", "Join rooms someone else runs");

  const render = () => {
    hubChoice.setAttribute("aria-checked", String(mode === "hub"));
    clientChoice.setAttribute("aria-checked", String(mode === "client"));
    hubRow.hidden = mode !== "client";
    shareRow.hidden = mode !== "hub";
    // The model is the hub's, so it's set where the hub runs: here, or not at all.
    model.section.hidden = mode !== "hub";
    button.textContent = !firstRun ? "Save and restart" : mode === "hub" ? "Start" : "Connect";
    renderSetsUp();
    where.textContent =
      mode === "hub" ? "Runs on this Mac, at 127.0.0.1" : hubUrl.trim() ? `Joins ${hubUrl.trim()}` : "Enter the hub's address";
    error.hidden = true;
  };
  hubField.addEventListener("input", () => {
    hubUrl = hubField.value;
    render();
  });
  rootButton.addEventListener("click", async () => {
    if (!inApp) return;
    const start = root.startsWith("~") ? snap.home + root.slice(1) : root;
    const picked = await invoke<string | null>("pick_folder", { start });
    if (picked) {
      root = tilde(picked, snap.home);
      rootPath.textContent = root;
    }
  });

  const agents = el("div", { class: "agents" }, el("span", { class: "hint" }, "Looking…"));
  const herdr = snap.herdr;
  const herdrPill = el(
    "span",
    { class: herdr.path ? "pill" : "pill missing" },
    el("span", { class: herdr.path ? "dot on" : "dot bad" }),
    herdr.bundled ? "herdr included" : herdr.path ? "herdr" : "herdr missing",
  );
  const scan = async () => {
    try {
      const found = inApp ? await invoke<{ frameworks?: Framework[] } | Framework[]>("scan_agents") : PREVIEW_AGENTS;
      const list = Array.isArray(found) ? found : (found.frameworks ?? []);
      const installed = list.filter((f) => f.installed);
      agents.replaceChildren(
        herdrPill,
        ...installed.map((f) =>
          el(
            "span",
            { class: "pill", title: f.launchable ? "" : "herdr can't start this one" },
            el("span", { class: f.launchable ? "dot on" : "dot" }),
            f.name,
            shortVersion(f.version) ? el("span", { class: "v" }, shortVersion(f.version)) : null,
          ),
        ),
      );
      if (installed.length === 0) {
        agents.append(el("span", { class: "hint" }, "No agent CLIs found. Install one, like Claude Code, to start agents here."));
      }
    } catch (e) {
      agents.replaceChildren(herdrPill, el("span", { class: "hint" }, String(e)));
    }
  };

  button.addEventListener("click", async () => {
    button.disabled = true;
    error.hidden = true;
    const settings: Settings = {
      mode,
      hubUrl: mode === "client" ? hubUrl.trim() : null,
      roots: [root.trim()],
      shareUsage: mode === "hub" && shareUsage,
    };
    try {
      // Saved first, so the hub that Start (re)starts reads it.
      if (mode === "hub" && inApp) await invoke<ModelView>("save_model", { model: model.value() });
      const setup = inApp ? await invoke<PathSetup>("start", { settings }) : null;
      loading(setup);
    } catch (e) {
      error.textContent = String(e);
      error.hidden = false;
      button.disabled = false;
    }
  });

  app.replaceChildren(
    el(
      "section",
      { class: "card" },
      head(
        firstRun
          ? "Rooms where you and your agents work together. Choose how this Mac takes part."
          : "Settings: how this Mac takes part, the model its agents use, and where they work. Saving restarts Mycelium.",
      ),
      el(
        "div",
        { class: "card-body" },
        el("div", {}, el("div", { class: "choices", role: "radiogroup", "aria-label": "How this Mac takes part" }, hubChoice, clientChoice), hubRow),
        model.section,
        el("div", {}, el("div", { class: "label" }, "Agents on this Mac"), agents),
        el(
          "div",
          {},
          el("div", { class: "label" }, "Folder agents may start in"),
          rootField,
          el("p", { class: "hint" }, "Agents you start from Mycelium work inside this folder."),
        ),
        shareRow,
        setsUp,
        error,
      ),
      el("div", { class: "card-foot" }, where, button),
    ),
  );
  hubRow.style.marginTop = "8px";
  render();
  void scan();
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
  const change = el("button", { class: "button ghost", type: "button" }, "Change");
  change.addEventListener("click", () => void onboarding());
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

interface Check {
  section: string;
  name: string;
  status: string;
  message: string;
  details: string[];
}

const PREVIEW_CHECKS: Check[] = [
  { section: "This Mac", name: "Hub", status: "ok", message: "answering at http://127.0.0.1:8000", details: [] },
  { section: "Agents", name: "herdr", status: "ok", message: "running (0.9.1)", details: [] },
  {
    section: "Models",
    name: "LLM connectivity",
    status: "error",
    message: "no model key set",
    details: ["Set one: mycelium config set llm.api_key <key>"],
  },
];

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
  const view = new URLSearchParams(location.search).get("view");
  if (view === "doctor") return doctor();
  const snap = await snapshot();
  if (view === "onboarding" || !snap.settings) await onboarding();
  else await loading();
}

void boot();
