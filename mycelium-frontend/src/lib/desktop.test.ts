// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { appJoinLink, desktopMachine, desktopVersion, inviteLink, isDesktop, settingsLink, terminalLink } from "@/lib/desktop";

describe("desktop links", () => {
  it("knows the app by its user agent", () => {
    const safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
    expect(isDesktop(safari)).toBe(false);
    expect(isDesktop(`${safari} MyceliumDesktop/0.1.0`)).toBe(true);
  });

  it("reads the app's version off the same mark", () => {
    const safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15";
    expect(desktopVersion(safari)).toBeNull();
    expect(desktopVersion(`${safari} MyceliumDesktop/3.0.14`)).toBe("3.0.14");
    expect(desktopVersion(`${safari} MyceliumDesktop/3.0.14-rc1`)).toBe("3.0.14-rc1");
  });

  it("asks the app for things by link, never by call", () => {
    expect(terminalLink("w9:p2")).toBe("mycelium://terminal?pane=w9%3Ap2");
    expect(settingsLink()).toBe("mycelium://settings");
    expect(appJoinLink("https://hub.example.com", "atlas")).toBe(
      "mycelium://join?hub=https%3A%2F%2Fhub.example.com&room=atlas",
    );
  });

  it("sends people an https link, which any chat app makes clickable", () => {
    expect(inviteLink("https://hub.example.com", "atlas migration")).toBe(
      "https://hub.example.com/join?room=atlas+migration",
    );
    expect(inviteLink("http://127.0.0.1:3717")).toBe("http://127.0.0.1:3717/join");
  });

  it("calls the machine a Mac on a Mac, and a computer elsewhere", () => {
    expect(desktopMachine("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) MyceliumDesktop/1.0")).toBe("Mac");
    expect(desktopMachine("Mozilla/5.0 (X11; Linux x86_64) MyceliumDesktop/1.0")).toBe("computer");
    expect(desktopMachine("Mozilla/5.0 (Windows NT 10.0; Win64; x64) MyceliumDesktop/1.0")).toBe("computer");
  });
});
