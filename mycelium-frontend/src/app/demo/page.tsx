// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Guided sample-coordination walkthrough — GUI replay (issues #374 / #315).
//
// Self-contained, offline replay of a recorded multi-agent negotiation so a new
// user watches Mycelium reach consensus before assembling one themselves. It
// mirrors the `mycelium demo` CLI command and reads the same fixtures (mirrored
// in ./scenarios.ts). Everything for the demo lives under src/app/demo/ — no
// shared components are modified.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MainTopBar } from "@/components/main-top-bar";
import {
  DEFAULT_SCENARIO,
  SCENARIOS,
  getScenario,
  type Action,
  type Scenario,
  type Step,
} from "./scenarios";

const AGENT_COLORS = ["#5dd4e0", "#c084fc", "#34d399", "#fbbf24", "#7dd3fc"];

const ACTION_STYLE: Record<Action, { glyph: string; color: string; label: string }> = {
  propose: { glyph: "◆", color: "var(--text)", label: "propose" },
  counter: { glyph: "◇", color: "#fbbf24", label: "counter" },
  accept: { glyph: "✓", color: "#34d399", label: "accept" },
  reject: { glyph: "✗", color: "#f87171", label: "reject" },
};

const STEP_PACE_MS = 1100;

function useAgentColors(scenario: Scenario): Record<string, string> {
  return useMemo(() => {
    const map: Record<string, string> = {};
    scenario.agents.forEach((a, i) => {
      map[a.handle] = AGENT_COLORS[i % AGENT_COLORS.length];
    });
    return map;
  }, [scenario]);
}

export default function DemoPage() {
  const [scenarioId, setScenarioId] = useState(DEFAULT_SCENARIO);
  const scenario = useMemo(() => getScenario(scenarioId), [scenarioId]);
  const colors = useAgentColors(scenario);

  // How many steps are revealed. 0 = nothing yet, steps.length = complete.
  const [revealed, setRevealed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);

  const total = scenario.steps.length;
  const done = revealed >= total;

  const reset = useCallback(() => {
    setPlaying(false);
    setRevealed(0);
  }, []);

  // Reset when the scenario changes.
  useEffect(() => {
    reset();
  }, [scenarioId, reset]);

  // Autoplay pacing.
  useEffect(() => {
    if (!playing) return;
    if (revealed >= total) {
      setPlaying(false);
      return;
    }
    const next = scenario.steps[revealed];
    const delay = next?.kind === "tick" ? STEP_PACE_MS : STEP_PACE_MS * 0.6;
    timer.current = setTimeout(() => setRevealed((r) => r + 1), delay);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [playing, revealed, total, scenario]);

  // Keep the newest step in view.
  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: "smooth" });
  }, [revealed]);

  const step = useCallback(() => {
    setPlaying(false);
    setRevealed((r) => Math.min(total, r + 1));
  }, [total]);

  const togglePlay = useCallback(() => {
    if (done) {
      setRevealed(0);
      setPlaying(true);
    } else {
      setPlaying((p) => !p);
    }
  }, [done]);

  const visibleSteps = scenario.steps.slice(0, revealed);
  const consensusStep = done ? scenario.steps[total - 1] : null;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar
        actions={<span className="caps-mono-sm text-muted">SAMPLE WALKTHROUGH</span>}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        {/* Scenario picker + controls */}
        <div className="flex flex-shrink-0 flex-wrap items-center gap-2 border-b border-border2 bg-paper px-6 py-2.5">
          {SCENARIOS.map((s) => {
            const active = s.id === scenarioId;
            return (
              <button
                key={s.id}
                onClick={() => setScenarioId(s.id)}
                title={s.tagline}
                className={`border px-3 py-1 caps-mono-sm transition-colors ${
                  active
                    ? "border-accent/60 bg-accent/[0.10] text-accent"
                    : "border-border text-text2 hover:text-text hover:border-border2"
                }`}
              >
                {s.title}
                {s.id === DEFAULT_SCENARIO ? "  ·  default" : ""}
              </button>
            );
          })}

          <div className="ml-auto flex items-center gap-2">
            <span className="caps-mono-sm text-dim tabular">
              {Math.min(revealed, total)}/{total}
            </span>
            <button
              onClick={togglePlay}
              className="border border-accent/40 bg-accent/[0.06] px-3 py-1 text-accent caps-mono-sm transition-colors hover:bg-accent/[0.12] hover:border-accent/60"
            >
              {playing ? "⏸ PAUSE" : done ? "↻ REPLAY" : revealed === 0 ? "▶ PLAY" : "▶ RESUME"}
            </button>
            <button
              onClick={step}
              disabled={done}
              className="border border-border px-3 py-1 text-text2 caps-mono-sm transition-colors hover:text-text hover:border-border2 disabled:opacity-40"
            >
              STEP
            </button>
            <button
              onClick={reset}
              disabled={revealed === 0}
              className="border border-border px-3 py-1 text-text2 caps-mono-sm transition-colors hover:text-text hover:border-border2 disabled:opacity-40"
            >
              RESET
            </button>
          </div>
        </div>

        <div className="grid flex-1 grid-cols-[280px_minmax(0,1fr)] overflow-hidden">
          {/* Left rail: scenario + issues */}
          <aside className="flex flex-col gap-5 overflow-y-auto border-r border-border bg-surface/40 px-5 py-5">
            <div>
              <div
                className="text-ui text-text"
                style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
              >
                {scenario.title}
              </div>
              <p className="mt-1 text-label leading-snug text-text2">{scenario.tagline}</p>
            </div>

            <Field label="Domain">{scenario.domain}</Field>
            <Field label="Model">{scenario.model}</Field>

            <div>
              <div className="caps-mono-sm mb-2 text-muted">Agents</div>
              <div className="flex flex-col gap-2">
                {scenario.agents.map((a) => (
                  <div key={a.handle} className="flex items-start gap-2">
                    <span
                      className="square-dot filled mt-1.5"
                      style={{ color: colors[a.handle] }}
                    />
                    <div className="min-w-0">
                      <span className="text-body" style={{ color: colors[a.handle] }}>
                        @{a.handle}
                      </span>
                      <div className="text-micro text-muted">{a.role}</div>
                      <div className="text-micro text-dim leading-snug">{a.blurb}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="caps-mono-sm mb-2 text-muted">Issues</div>
              <div className="flex flex-col gap-2">
                {scenario.issues.map((iss) => (
                  <div key={iss.key}>
                    <div className="text-label text-text">{iss.label}</div>
                    <div className="text-micro text-dim">{iss.options.join("  ·  ")}</div>
                  </div>
                ))}
              </div>
            </div>
          </aside>

          {/* Stream */}
          <section ref={streamRef} className="overflow-y-auto px-6 py-5">
            {revealed === 0 ? (
              <div className="flex h-full items-center justify-center text-center italic text-muted">
                Press <span className="mx-1 not-italic text-accent">▶ PLAY</span> to watch{" "}
                {scenario.agents.length} agents negotiate to{" "}
                {scenario.metrics.consensus ? "consensus" : "a structured impasse"}.
              </div>
            ) : (
              <div className="mx-auto flex max-w-3xl flex-col gap-2.5">
                {visibleSteps.map((s, i) => (
                  <StepRow key={i} step={s} colors={colors} />
                ))}
                {consensusStep && <ReproducePanel scenario={scenario} />}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="caps-mono-sm text-muted">{label}</div>
      <div className="text-body text-text">{children}</div>
    </div>
  );
}

function StepRow({ step, colors }: { step: Step; colors: Record<string, string> }) {
  if (step.kind === "system") {
    return <div className="text-label text-muted">· {step.text}</div>;
  }

  if (step.kind === "seed") {
    return (
      <div className="rounded-sm border border-border bg-surface/60 px-3 py-2">
        <div className="caps-mono-sm mb-1 text-muted">seed task</div>
        <div className="text-body text-text2">{step.text}</div>
      </div>
    );
  }

  if (step.kind === "join") {
    const color = colors[step.agent ?? ""] ?? "var(--text)";
    return (
      <div className="text-body">
        <span style={{ color }}>@{step.agent}</span>{" "}
        <span className="text-muted">joined</span>{" "}
        <span className="text-text2">— {step.intent}</span>
      </div>
    );
  }

  if (step.kind === "tick") {
    const color = colors[step.agent ?? ""] ?? "var(--text)";
    const action = ACTION_STYLE[step.action ?? "propose"];
    return (
      <div className="rounded-sm border border-border bg-surface/30 px-3 py-2">
        <div className="flex items-baseline gap-2">
          <span className="text-micro text-dim tabular">R{step.round}</span>
          <span style={{ color: action.color }}>{action.glyph}</span>
          <span className="text-body" style={{ color }}>
            @{step.agent}
          </span>
          <span className="caps-mono-sm" style={{ color: action.color }}>
            {action.label}
          </span>
        </div>
        <div className="mt-1 text-body text-text2">{step.text}</div>
        {step.offer && Object.keys(step.offer).length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {Object.entries(step.offer).map(([k, v]) => (
              <span key={k} className="border border-border px-1.5 py-0.5 text-micro text-muted">
                {k}={v}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (step.kind === "consensus") {
    return <ConsensusPanel step={step} />;
  }

  return null;
}

function ConsensusPanel({ step }: { step: Step }) {
  const reached = !!step.reached;
  const accent = reached ? "#34d399" : "#fbbf24";
  return (
    <div className="mt-2 rounded-sm border px-4 py-3" style={{ borderColor: accent }}>
      <div className="caps-mono mb-2" style={{ color: accent }}>
        {reached ? `✓ CONSENSUS · ${step.rounds} rounds` : `⚠ STRUCTURED IMPASSE · ${step.rounds} rounds`}
      </div>

      <div className="flex flex-col gap-1">
        {Object.entries(step.assignments ?? {}).map(([k, v]) => {
          const unresolved = typeof v === "string" && v.startsWith("UNRESOLVED");
          return (
            <div key={k} className="flex items-baseline justify-between gap-4">
              <span className="text-label text-muted">{k}</span>
              <span className="text-body" style={{ color: unresolved ? "#fbbf24" : "var(--text)" }}>
                {v}
              </span>
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-body italic text-text2">{step.summary}</p>

      {step.escalation && (
        <div className="mt-3 rounded-sm border border-border bg-surface/50 px-3 py-2 text-label text-text2">
          {step.escalation}
        </div>
      )}

      <div className="mt-4">
        <div className="caps-mono-sm mb-1.5 text-muted">
          compiled plan → <span className="text-accent">{step.plan_file}</span>
        </div>
        <div className="flex flex-col gap-1">
          {(step.tasks ?? []).map((t, i) => (
            <div key={i} className="text-body text-text2">
              <span className="text-dim">- [ ]</span> {t}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ReproducePanel({ scenario }: { scenario: Scenario }) {
  const handles = scenario.agents.map((a) => a.handle);
  const lines = [
    `mycelium room create ${scenario.room}`,
    `mycelium room use ${scenario.room}`,
    ...handles.map((h) => `mycelium agent create --handle ${h} -r ${scenario.room}`),
    `mycelium session create -r ${scenario.room}`,
    ...handles.map((h) => `mycelium session join -H @${h} -m "<your position>" -r ${scenario.room}`),
    `mycelium watch ${scenario.room}`,
  ];
  return (
    <div className="mt-3 rounded-sm border border-accent/40 bg-accent/[0.04] px-4 py-3">
      <div className="caps-mono-sm mb-1 text-accent">What you just watched — reproduce it yourself</div>
      <p className="mb-2 text-label text-muted">
        Or provision this exact scenario as a real room:{" "}
        <span className="text-text2">mycelium demo --scenario {scenario.id} --live</span>
      </p>
      <pre className="overflow-x-auto whitespace-pre-wrap text-micro text-text2">{lines.join("\n")}</pre>
    </div>
  );
}
