// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useRef, useState } from "react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { useCustomThemes } from "@/components/custom-theme";
import { setClientSetting } from "@/lib/client-settings";
import {
  CUSTOM_THEME,
  customThemeProblems,
  parseCustomTheme,
  templateFrom,
  themeJson,
  type CustomTheme,
} from "@/lib/custom-themes";
import { describeProblem } from "@/lib/theme-contrast";
import { modeOf, themeById } from "@/lib/themes";
import { Note, Row } from "./settings-ui";

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const fileName = (name: string) => `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "theme"}.json`;

/** What came of the last import: why it was refused, or what it reads like. */
type Outcome = { kind: "refused"; errors: string[] } | { kind: "added"; theme: CustomTheme; problems: string[] };

/**
 * Themes someone brings as JSON: add one from a file or pasted text, use it,
 * download it again, or remove it. A theme is checked as it comes in: one that
 * isn't valid is refused with every reason, and one whose words would fall
 * under AA contrast is added with those pairs named, since it's their screen.
 * "Download this theme" gives the theme showing now as JSON to start from.
 */
export function CustomThemesRow() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const { themes, active } = useCustomThemes();
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const switchTo = (t: CustomTheme) => {
    setClientSetting("appearance.custom-theme", t.id);
    setTheme(CUSTOM_THEME);
  };

  const add = (raw: string) => {
    const parsed = parseCustomTheme(raw);
    if (!parsed.ok) {
      setOutcome({ kind: "refused", errors: parsed.errors });
      return;
    }
    const next = parsed.theme;
    setClientSetting("appearance.custom-themes", [...themes.filter((t) => t.id !== next.id), next]);
    switchTo(next);
    setOutcome({ kind: "added", theme: next, problems: customThemeProblems(next).map(describeProblem) });
    setText("");
    setPasting(false);
  };

  const remove = (t: CustomTheme) => {
    setClientSetting("appearance.custom-themes", themes.filter((x) => x.id !== t.id));
    if (active?.id === t.id) {
      setClientSetting("appearance.custom-theme", "");
      if (theme === CUSTOM_THEME) setTheme("dark");
    }
    if (outcome?.kind === "added" && outcome.theme.id === t.id) setOutcome(null);
  };

  const downloadShowing = () => {
    const showing = theme === CUSTOM_THEME ? active?.name : themeById(resolvedTheme)?.label;
    const name = `${showing ?? "Mycelium"} (copy)`;
    const style = getComputedStyle(document.documentElement);
    download(
      fileName(name),
      templateFrom((v) => style.getPropertyValue(v), name, modeOf(resolvedTheme, active?.mode)),
    );
  };

  return (
    <Row
      id="general.custom-themes"
      label="Your themes"
      help="Bring a theme as JSON: the app's colors by name, as hex. To start, download the theme showing now, change its colors and add it back."
      below={
        <div className="space-y-3">
          {pasting && (
            <div className="space-y-2">
              <textarea
                aria-label="Theme JSON"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={8}
                spellCheck={false}
                placeholder={'{ "name": "Midnight", "mode": "dark", "colors": { "bg": "#0b1020", … } }'}
                className="w-full rounded-lg border border-border bg-bg p-2 font-mono text-micro text-text outline-none focus:border-accent"
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={() => add(text)} disabled={!text.trim()}>
                  Add theme
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPasting(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
          {outcome?.kind === "refused" && (
            <Note tone="error">
              That theme wasn&apos;t added: {outcome.errors.join(" ")}
            </Note>
          )}
          {outcome?.kind === "added" &&
            (outcome.problems.length ? (
              <Note>
                Added &ldquo;{outcome.theme.name}&rdquo; and switched to it. Some words in it are hard to read, under
                the 4.5:1 contrast the built-in themes keep: {outcome.problems.join("; ")}.
              </Note>
            ) : (
              <Note>
                Added &ldquo;{outcome.theme.name}&rdquo; and switched to it. Its words all read at 4.5:1 or better.
              </Note>
            ))}
          {themes.length > 0 && (
            <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Your themes">
              {themes.map((t) => {
                const problems = customThemeProblems(t).length;
                const showing = theme === CUSTOM_THEME && active?.id === t.id;
                return (
                  <li key={t.id} className="flex items-center gap-3 px-3 py-2">
                    <span className="flex shrink-0 gap-0.5" aria-hidden>
                      {[t.colors.bg, t.colors.text, t.colors.accent].map((c, i) => (
                        <span key={i} className="size-3 rounded-sm border border-border" style={{ background: c }} />
                      ))}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-label text-text">
                      {t.name}
                      <span className="ml-2 text-micro text-faint">
                        {t.mode}
                        {problems ? ` · ${problems} ${problems === 1 ? "pair" : "pairs"} under 4.5:1` : ""}
                      </span>
                    </span>
                    {showing ? (
                      <span className="text-micro text-accent">Showing</span>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => switchTo(t)}>
                        Use
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => download(fileName(t.name), themeJson(t))}>
                      Download
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(t)} aria-label={`Remove ${t.name}`}>
                      Remove
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      }
    >
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" size="sm" onClick={downloadShowing}>
          Download this theme
        </Button>
        <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
          Add from a file
        </Button>
        <Button variant="outline" size="sm" onClick={() => setPasting((p) => !p)} aria-expanded={pasting}>
          Paste JSON
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          aria-label="Theme file"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) add(await file.text());
          }}
        />
      </div>
    </Row>
  );
}
