// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Check } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { desktopMachine } from "@/lib/desktop";
import {
  appCall,
  saveAndRestart,
  useApp,
  type AppState,
  type Check as HealthCheck,
  type HubSettings,
  type ModelView,
} from "@/lib/desktop-app";
import { ActionError, RestartSave, useAppAction } from "./app-save";
import { Note, Row, Section, Segmented, SettingsPage, Value } from "./settings-ui";

type ProviderId = "anthropic" | "openai" | "openrouter" | "ollama" | "custom";

interface Provider {
  id: ProviderId;
  name: string;
  /** Suggestions, the first the default; the same ones `mycelium install` offers. */
  models: string[];
  /** The key field's placeholder; null for a provider that needs no key. */
  key: string | null;
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
  { id: "ollama", name: "Ollama", models: ["ollama/llama3.3", "ollama/mistral", "ollama/qwen2.5"], key: null, baseUrl: "http://localhost:11434" },
  { id: "custom", name: "Other", models: [], key: "If it needs one", baseUrl: "" },
];

const MODELS_DOC = "https://mycelium-io.github.io/mycelium/guides.html#models";

function providerOf(model: string | null): Provider {
  const prefix = (model ?? "").split("/")[0];
  return PROVIDERS.find((p) => p.id === prefix) ?? (model ? PROVIDERS[PROVIDERS.length - 1] : PROVIDERS[0]);
}

const field =
  "w-72 rounded-md border border-border bg-bg px-2.5 py-1 font-mono text-micro text-text outline-none focus:border-accent";

/** The model the hub's engines think with: chosen here for a hub on this
 *  machine, shown as the team's hub has it otherwise. Your own agents never
 *  use it, and the page says so, since that's what people get wrong. */
export function AppModelPage() {
  const { data: state } = useApp<AppState>("get_state");
  const client = state?.settings?.mode === "client";
  return (
    <SettingsPage
      title="Engines' model"
      scope={
        client
          ? "Your team's hub runs its engines with this model, set on that hub. Your own agents, like Claude Code, don't use it."
          : "Personas, workers, the synthesizer and the verifier think with this model. Your own agents, like Claude Code, don't use it."
      }
    >
      {state === undefined ? null : client ? <HubModel /> : <ModelForm state={state} />}
    </SettingsPage>
  );
}

function HubModel() {
  const { data: hub, error } = useApp<HubSettings>("get_hub_settings");
  if (error) return <Note tone="error">Couldn&apos;t ask your team&apos;s hub. {String(error.message ?? error)}</Note>;
  if (!hub) return <Note>Asking your team&apos;s hub…</Note>;
  const m = hub.model;
  const provider = m.provider ? (PROVIDERS.find((p) => p.id === m.provider)?.name ?? m.provider) : "Not set";
  return (
    <Section title="On your team's hub" note="To change it, change it on that hub.">
      <Row label="Provider">
        <Value>{provider}</Value>
      </Row>
      <Row label="Model">
        <Value mono>{m.model ?? "Not set"}</Value>
      </Row>
      <Row label="API key">
        <Value>{m.has_key ? "Set" : "Not set"}</Value>
      </Row>
      {m.custom_endpoint && (
        <Row label="Address">
          <Value>Set on the hub</Value>
        </Row>
      )}
    </Section>
  );
}

function ModelForm({ state }: { state: AppState }) {
  const { data: saved } = useApp<ModelView>("get_model");
  if (!saved) return <Note>Reading the model…</Note>;
  return <ModelFields state={state} saved={saved} />;
}

/** The form, starting from what's saved. */
function ModelFields({ state, saved }: { state: AppState; saved: ModelView }) {
  const machine = desktopMachine();
  const [provider, setProvider] = useState<Provider>(() => providerOf(saved.model));
  const [model, setModel] = useState(() => saved.model ?? providerOf(saved.model).models[0] ?? "");
  const [baseUrl, setBaseUrl] = useState(() => saved.base_url ?? providerOf(saved.model).baseUrl ?? "");
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const { busy, error, run } = useAppAction();

  const savedFor = providerOf(saved.model).id;
  const hasSaved = saved.has_key && provider.id === savedFor;
  const pick = (id: ProviderId) => {
    const p = PROVIDERS.find((x) => x.id === id) ?? PROVIDERS[0];
    setProvider(p);
    setModel(p.models[0] ?? "");
    setBaseUrl(p.baseUrl ?? "");
  };
  const body = (): Record<string, string> => {
    const out: Record<string, string> = {
      model: model.trim(),
      base_url: provider.baseUrl === undefined ? "" : baseUrl.trim(),
    };
    // Left empty, the saved key stays: the page never had it to send back.
    // Unless the provider changed: the old key is the old provider's.
    if (provider.key !== null && key.trim()) out.api_key = key.trim();
    else if (provider.key !== null && saved.has_key && provider.id !== savedFor) out.api_key = "";
    return out;
  };
  const save = () =>
    void run(async () => {
      await appCall("save_model", { model: body() });
      if (state.settings) await saveAndRestart(state.settings);
    });

  return (
    <>
      <Section title="Model">
        <Row label="Provider">
          <Segmented label="Provider" value={provider.id} onChange={pick} options={PROVIDERS.map((p) => ({ value: p.id, label: p.name }))} />
        </Row>
        {provider.key !== null && (
          <Row
            id="model.key"
            label="API key"
            help={`${provider.keyFrom ? `Get one at ${provider.keyFrom}. ` : ""}It stays on this ${machine}.`}
          >
            {hasSaved && !replacing ? (
              <span className="flex items-center gap-2 text-label text-text">
                <Check className="size-3.5 text-green" aria-hidden />
                Key saved
                <Button variant="link" size="xs" onClick={() => setReplacing(true)}>
                  Replace
                </Button>
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder={provider.key}
                  aria-label="API key"
                  className={field}
                />
                {hasSaved && (
                  <Button
                    variant="link"
                    size="xs"
                    onClick={() => {
                      setReplacing(false);
                      setKey("");
                    }}
                  >
                    Keep the saved key
                  </Button>
                )}
              </span>
            )}
          </Row>
        )}
        {provider.baseUrl !== undefined && (
          <Row id="model.address" label="Address" help="Your provider's URL.">
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://…"
              spellCheck={false}
              autoCapitalize="none"
              aria-label="Address"
              className={field}
            />
          </Row>
        )}
        <Row
          id="model.model"
          label="Model"
          help={
            <>
              Any model your provider offers.{" "}
              <a href={MODELS_DOC} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                Learn more about models
              </a>
            </>
          }
        >
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            list="app-model-suggestions"
            spellCheck={false}
            autoCapitalize="none"
            aria-label="Model"
            className={field}
          />
          <datalist id="app-model-suggestions">
            {provider.models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </Row>
        <ModelStatus />
      </Section>
      <div className="mt-4 flex items-center justify-end gap-3">
        <RestartSave onSave={save} busy={busy} />
      </div>
      <ActionError error={error} />
    </>
  );
}

/** What the health check says when no model is set (`doctor.py`). */
const MODEL_UNSET = "Engines' model not set";

/** Whether the model is answering, from the health check. No model is fine,
 *  so the check says ok, but it isn't connected either. */
function ModelStatus() {
  const { data, error } = useApp<{ checks: HealthCheck[] }>("run_doctor");
  const check = data?.checks.find((c) => c.name === "LLM connectivity");
  const unset = check?.message === MODEL_UNSET;
  const text = error
    ? "Couldn't check the model."
    : !data
      ? "Checking the model…"
      : !check
        ? "Start Mycelium to check the model."
        : unset
          ? "Not set. Engines can't answer until you add one."
          : check.status === "ok"
            ? "Connected."
            : `Not connected: ${check.message}. ${check.details[check.details.length - 1] ?? ""}`;
  const tone = !check || unset ? "text-muted-foreground" : check.status === "ok" ? "text-green" : "text-red";
  return (
    <Row label="Status">
      <span className={`text-micro ${tone}`}>{text}</span>
    </Row>
  );
}
