// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// This machine's themes: the files in ~/.mycelium/themes/ and ~/.mycelium/theme.json
// (which one the app shows), the same ones `mycelium theme` writes. Served by
// the app's own server, never the hub, and only when the desktop app runs it for
// its person and says where the folder is (MYCELIUM_THEMES_DIR). Anywhere else
// there's nothing here, and the app keeps the themes this browser has.
//
// GET  → { themes, current }: every file that's a theme (by the app's own rules),
//        and the picked id, or null.
// PUT  { theme } → writes the pick, so the CLI and the app agree.
//
// The open app hears that either changed on its held stream (the `themes`
// feed, `lib/theme-files.ts`), not by asking here.

import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";
import { CUSTOM_THEME, parseCustomTheme, type CustomTheme } from "@/lib/custom-themes";
import { pickFile, themesFolder as folder } from "@/lib/theme-files";
import { SYSTEM, themeById } from "@/lib/themes";

export const dynamic = "force-dynamic";

async function readThemes(dir: string): Promise<CustomTheme[]> {
  let names: string[];
  try {
    names = await fs.readdir(dir);
  } catch {
    return [];
  }
  const found = new Map<string, CustomTheme>();
  for (const name of names.sort()) {
    if (!name.endsWith(".json") || name.startsWith(".")) continue;
    try {
      const parsed = parseCustomTheme(await fs.readFile(path.join(dir, name), "utf8"));
      if (parsed.ok && !found.has(parsed.theme.id)) found.set(parsed.theme.id, parsed.theme);
    } catch {
      // A file that can't be read is left out, as one that isn't a theme is.
    }
  }
  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name));
}

async function readPick(dir: string): Promise<string | null> {
  try {
    const data = JSON.parse(await fs.readFile(pickFile(dir), "utf8")) as { theme?: unknown };
    return typeof data.theme === "string" && data.theme ? data.theme : null;
  } catch {
    return null;
  }
}

export async function GET(): Promise<Response> {
  const dir = folder();
  if (!dir) return NextResponse.json({ themes: [], current: null, available: false });
  const [themes, current] = await Promise.all([readThemes(dir), readPick(dir)]);
  return NextResponse.json({ themes, current, available: true });
}

export async function PUT(req: Request): Promise<Response> {
  const dir = folder();
  if (!dir) return NextResponse.json({ detail: "This app keeps no theme files." }, { status: 404 });
  let body: { theme?: unknown };
  try {
    body = (await req.json()) as { theme?: unknown };
  } catch {
    return NextResponse.json({ detail: "Send { theme }." }, { status: 422 });
  }
  const theme = typeof body.theme === "string" ? body.theme : "";
  const known =
    theme === SYSTEM ||
    (!!themeById(theme) && theme !== CUSTOM_THEME) ||
    (await readThemes(dir)).some((t) => t.id === theme);
  if (!known) return NextResponse.json({ detail: `There's no theme ${theme}.` }, { status: 404 });
  const file = pickFile(dir);
  const tmp = `${file}.${process.pid}.tmp`;
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(tmp, `${JSON.stringify({ theme }, null, 2)}\n`);
  await fs.rename(tmp, file);
  return NextResponse.json({ theme });
}
