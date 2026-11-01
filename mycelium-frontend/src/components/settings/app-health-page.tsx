// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Button } from "@/components/ui/button";
import { desktopMachine } from "@/lib/desktop";
import { appCall, useApp, type Check } from "@/lib/desktop-app";
import { cn } from "@/lib/utils";
import { ActionError, useAppAction } from "./app-save";
import { Note, Section, SettingsPage } from "./settings-ui";

const MARK: Record<string, { glyph: string; tone: string }> = {
  ok: { glyph: "✓", tone: "text-green" },
  warning: { glyph: "!", tone: "text-yellow" },
  info: { glyph: "i", tone: "text-muted-foreground" },
};

/** Each part Mycelium runs on this machine, and whether it's working
 *  (`mycelium doctor --mode desktop`). */
export function AppHealthPage() {
  const machine = desktopMachine();
  const { data, error: readError, isValidating, mutate } = useApp<{ checks: Check[] }>("run_doctor");
  const { error, run } = useAppAction();
  const sections = new Map<string, Check[]>();
  for (const c of data?.checks ?? []) sections.set(c.section, [...(sections.get(c.section) ?? []), c]);
  const problems = (data?.checks ?? []).filter((c) => !["ok", "info"].includes(c.status)).length;

  return (
    <SettingsPage
      title="Health check"
      scope={
        data
          ? problems
            ? `${problems} thing${problems === 1 ? "" : "s"} to look at.`
            : "Everything checks out."
          : `Each part Mycelium runs on this ${machine}, and whether it's working.`
      }
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={() => void run(() => appCall("open_log"))}>
            Show log
          </Button>
          <Button variant="outline" size="sm" onClick={() => void mutate()} disabled={isValidating}>
            {isValidating ? "Checking…" : "Check again"}
          </Button>
        </>
      }
    >
      {readError && <Note tone="error">{String(readError.message ?? readError)}</Note>}
      {!data && !readError && <Note>Checking…</Note>}
      {[...sections].map(([title, checks]) => (
        <Section key={title} title={title}>
          {checks.map((c) => {
            const mark = MARK[c.status] ?? { glyph: "✗", tone: "text-red" };
            return (
              <div key={c.name} className="flex gap-3 px-4 py-3">
                <span aria-label={c.status} className={cn("w-3 flex-shrink-0 text-center text-label", mark.tone)}>
                  {mark.glyph}
                </span>
                <div className="min-w-0 text-label">
                  <span className="font-medium text-text">{c.name}</span>{" "}
                  <span className="text-muted-foreground">{c.message}</span>
                  {c.details.map((d) => (
                    <p key={d} className="mt-0.5 font-mono text-micro text-muted-foreground">
                      {d}
                    </p>
                  ))}
                </div>
              </div>
            );
          })}
        </Section>
      ))}
      <ActionError error={error} />
    </SettingsPage>
  );
}
