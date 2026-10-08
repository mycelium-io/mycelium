import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/account-menu", () => ({ AccountMenu: () => <span>account</span> }));
vi.mock("@/components/notification-bell", () => ({ NotificationBell: () => <span>bell</span> }));
vi.mock("@/components/key-badge", () => ({ KeyBadge: () => null }));

import { TitleBar, hubLabel } from "./title-bar";

describe("hubLabel", () => {
  it("names a hub on this computer, never by its port", () => {
    expect(hubLabel("localhost:59370", false)).toBe("This computer");
    expect(hubLabel("127.0.0.1:8000", true, "Mac")).toBe("This Mac");
    expect(hubLabel("127.0.0.1:8000", true, "computer")).toBe("This computer");
    expect(hubLabel("[::1]:3000", false)).toBe("This computer");
  });

  it("names any other hub by its host alone", () => {
    expect(hubLabel("hub.example.com:8443", false)).toBe("hub.example.com");
    expect(hubLabel("hub.example.com", true)).toBe("hub.example.com");
  });
});

describe("TitleBar", () => {
  it("leads home, then shows where you are, and who you are on the right", () => {
    render(<TitleBar crumb={<span>atlas</span>} right={<span>theme</span>} />);
    expect(screen.getByRole("link", { name: /Mycelium/ })).toHaveAttribute("href", "/");
    expect(screen.getByText("atlas")).toBeInTheDocument();
    expect(screen.getByText("theme")).toBeInTheDocument();
    expect(screen.getByText("account")).toBeInTheDocument();
  });

  it("draws no separator without a page to name", () => {
    render(<TitleBar />);
    expect(screen.queryByText("/")).not.toBeInTheDocument();
  });
});
