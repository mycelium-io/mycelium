// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Content for the guided CLI install surface.
 *
 * The browser can't run an install — it talks to the backend API, not the
 * user's shell — so the flow hands over commands to paste and infers that they
 * worked from the hub answering. Keeping the copy here (rather than inline in
 * the panel) keeps the strings testable and single-sourced with the README.
 */

export const DOCS_URL = "https://mycelium-io.github.io/mycelium";

/** Step 1: fetch the CLI — the same one-liner the README and docs site carry. */
export const CLI_INSTALL_COMMAND = `curl -fsSL ${DOCS_URL}/install.sh | bash`;

/** Step 2: pull the images, prompt for the LLM key, write ~/.mycelium/config.toml. */
export const STACK_INSTALL_COMMAND = "mycelium install";

export type Platform = "macos" | "linux" | "windows" | "unknown";

export interface PlatformInfo {
  id: Exclude<Platform, "unknown">;
  label: string;
  /** Extra shown under the commands when this platform is selected. */
  note?: string;
}

export const PLATFORMS: PlatformInfo[] = [
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
  {
    id: "windows",
    label: "Windows",
    note: "Run both commands inside WSL. The installer and the Docker stack are POSIX-only, and the hub then answers on localhost for the browser too.",
  },
];

/**
 * Best-effort OS from a user-agent string. Phones and tablets read as
 * `unknown` — nothing installs there — and their UAs name a desktop family
 * ("like Mac OS X", "Linux; Android"), so they're matched first.
 */
export function detectPlatform(userAgent: string | null | undefined): Platform {
  const ua = (userAgent ?? "").toLowerCase();
  if (!ua) return "unknown";
  if (/android|iphone|ipad|ipod/.test(ua)) return "unknown";
  if (/windows|win32|win64/.test(ua)) return "windows";
  if (/mac os|macintosh/.test(ua)) return "macos";
  if (/linux|x11|cros/.test(ua)) return "linux";
  return "unknown";
}

export interface NextStep {
  title: string;
  body: string;
  command: string;
  /** Where the docs explain this step in full. */
  href: string;
}

/** What to do once the hub answers — the shape of a first session. */
export const NEXT_STEPS: NextStep[] = [
  {
    title: "Create a room",
    body: "A room is the shared space for agents, memory, and the plan.",
    command: "mycelium room create my-project && mycelium room use my-project",
    href: `${DOCS_URL}/index.html#rooms`,
  },
  {
    title: "Add an agent",
    body: "One per role. Each becomes a citizen of the room you can @mention.",
    command: 'mycelium agent create planner --description "Sprint planner"',
    href: `${DOCS_URL}/adapters.html`,
  },
  {
    title: "Keep the session resident",
    body: "The loop is the wake: await → reason → respond, keeping context between turns.",
    command: "mycelium await --loop",
    href: `${DOCS_URL}/reference.html`,
  },
];
