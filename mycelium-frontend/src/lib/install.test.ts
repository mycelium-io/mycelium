// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  agentHandoffPrompt,
  CLI_INSTALL_COMMAND,
  PLATFORMS,
  configSetCommand,
  detectPlatform,
  hubSetupCommand,
  hubSetupPrompt,
} from "@/lib/install";

const UA = {
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
  windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
  android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Mobile Safari/537.36",
};

describe("detectPlatform", () => {
  it("reads the desktop families", () => {
    expect(detectPlatform(UA.mac)).toBe("macos");
    expect(detectPlatform(UA.linux)).toBe("linux");
    expect(detectPlatform(UA.windows)).toBe("windows");
  });

  // Both phone UAs name a desktop family ("like Mac OS X", "Linux; Android"),
  // and neither can run the installer — so neither may match one.
  it("claims no platform for phones or a missing user agent", () => {
    expect(detectPlatform(UA.iphone)).toBe("unknown");
    expect(detectPlatform(UA.android)).toBe("unknown");
    expect(detectPlatform("")).toBe("unknown");
    expect(detectPlatform(null)).toBe("unknown");
  });
});

describe("install content", () => {
  it("carries the same install one-liner the README and docs site publish", () => {
    expect(CLI_INSTALL_COMMAND).toBe(
      "curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash",
    );
  });

  it("points the config command at whatever hub URL it's given", () => {
    expect(configSetCommand("http://hub.example.com:8000")).toBe(
      "mycelium config set server.api_url http://hub.example.com:8000 && mycelium config apply",
    );
  });

  it("generates a hub-aware setup handoff instead of a generic documentation link", () => {
    const prompt = hubSetupPrompt({
      hubUrl: "https://hub.example.com",
      authRequired: false,
      principal: "avery",
    });
    expect(prompt).toContain("https://hub.example.com");
    expect(prompt).toContain("mycelium iam avery");
    expect(prompt).not.toContain("agents.md");
  });

  it("uses the signed-in identity rather than a browser-selected one on a gated hub", () => {
    const setup = hubSetupCommand({
      hubUrl: "https://hub.example.com",
      authRequired: true,
      principal: "avery",
    });
    expect(setup).toContain("mycelium login");
    expect(setup).toContain("mycelium whoami");
    expect(setup).not.toContain("mycelium iam avery");
  });

  it("hands an existing coding session the room, hub, and first collaboration step", () => {
    const prompt = agentHandoffPrompt({
      hubUrl: "https://hub.example.com",
      authRequired: false,
      principal: "avery",
      roomName: "atlas",
    });
    expect(prompt).toContain("room `atlas`");
    expect(prompt).toContain("--room atlas --owner avery");
    expect(prompt).toContain("mycelium board --room atlas");
    expect(prompt).toContain("--timeout 30");
  });

  it("notes the WSL constraint on Windows only", () => {
    const windows = PLATFORMS.find(p => p.id === "windows");
    expect(windows?.note).toMatch(/WSL/);
    expect(PLATFORMS.filter(p => p.note)).toHaveLength(1);
  });
});
