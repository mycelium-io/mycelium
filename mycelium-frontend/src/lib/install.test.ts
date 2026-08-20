// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  CLI_INSTALL_COMMAND,
  NEXT_STEPS,
  PLATFORMS,
  STACK_INSTALL_COMMAND,
  detectPlatform,
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
    expect(STACK_INSTALL_COMMAND).toBe("mycelium install");
  });

  it("notes the WSL constraint on Windows only", () => {
    const windows = PLATFORMS.find(p => p.id === "windows");
    expect(windows?.note).toMatch(/WSL/);
    expect(PLATFORMS.filter(p => p.note)).toHaveLength(1);
  });

  it("points every next step at the docs", () => {
    expect(NEXT_STEPS.length).toBeGreaterThan(0);
    for (const step of NEXT_STEPS) {
      expect(step.href).toMatch(/^https:\/\/mycelium-io\.github\.io\/mycelium\//);
      expect(step.command).toMatch(/^mycelium /);
    }
  });
});
