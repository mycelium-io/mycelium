// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Button } from "@/components/ui/button";
import { RunDetail, WIDGET_COLOR, WidgetValue } from "@/components/widgets-card";
import { WidgetIcon } from "@/components/widget-icon";
import { desktopMachine } from "@/lib/desktop";
import { appCall } from "@/lib/desktop-app";
import { cn } from "@/lib/utils";
import { lookOf, notesOf, useWidgets } from "@/lib/widgets";
import { ActionError, useAppAction } from "./app-save";
import { Note, Section, SettingsPage } from "./settings-ui";

/** How a first widget reads in the config file, for a page with none. */
const EXAMPLE = `[[statusline.widget]]
label = "disk free"
icon = "hard-drive"
command = "df -h / | awk 'NR==2 {print $4}'"
every = "5m"`;

/** The Widgets card's own page: the config file they come from, a way to open
 *  it, and how each one last ran. */
export function AppWidgetsPage() {
  const machine = desktopMachine();
  const data = useWidgets();
  const { error, run } = useAppAction();
  const widgets = data?.widgets ?? [];

  return (
    <SettingsPage
      title="Widgets"
      scope={`Your own readouts at the foot of the rooms list. Mycelium runs each command on this ${machine}, from your config file, and nothing else can add one.`}
      actions={
        <Button variant="outline" size="sm" onClick={() => void run(() => appCall("open_widgets_config"))}>
          Open in editor
        </Button>
      }
    >
      <Section title="Config file">
        <div className="px-4 py-3 font-mono text-micro text-muted-foreground">{data?.config ?? "~/.mycelium/config.toml"}</div>
      </Section>
      {data?.error && <Note tone="error">{data.error}</Note>}
      <Section title="Widgets">
        {!data && <div className="px-4 py-3 text-label text-muted-foreground">Reading…</div>}
        {data && widgets.length === 0 && (
          <div className="px-4 py-3 text-label text-muted-foreground">
            <p>No widgets yet, so there&apos;s no card. Add one to your config file under{" "}
              <code className="font-mono text-text">[statusline]</code>:
            </p>
            <pre className="mt-2 rounded-md bg-bg p-2 font-mono text-micro text-text">{EXAMPLE}</pre>
          </div>
        )}
        {widgets.map((w, i) => {
          const look = lookOf(w);
          const notes = notesOf(w);
          return (
            <div key={`${i}-${w.label}`} className="flex gap-3 px-4 py-3">
              <WidgetIcon
                name={look.icon}
                className={cn("mt-0.5", look.color ? WIDGET_COLOR[look.color] : "text-faint")}
              />
              <div className="min-w-0 flex-1 text-label">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-text">{w.label}</span>
                  <WidgetValue widget={w} />
                </div>
                <div className="mt-0.5 text-micro text-muted-foreground">
                  <RunDetail widget={w} />
                </div>
                {/* A field the app left out: said here, quietly, and nowhere else. */}
                {notes.map((note, n) => (
                  <div key={n} className="mt-0.5 text-micro text-faint">
                    {note}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </Section>
      <ActionError error={error} />
    </SettingsPage>
  );
}
