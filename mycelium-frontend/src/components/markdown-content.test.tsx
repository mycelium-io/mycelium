// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MarkdownContent } from "@/components/markdown-content";

describe("<MarkdownContent /> memory links", () => {
  it("renders a wikilink as a clickable chip carrying its target", async () => {
    const onLinkClick = vi.fn();
    render(<MarkdownContent onLinkClick={onLinkClick}>{"See [[decisions/db]]."}</MarkdownContent>);

    await userEvent.click(screen.getByRole("button", { name: "decisions/db" }));

    expect(onLinkClick).toHaveBeenCalledWith("decisions/db");
  });

  it("resolves a myc:// URI to the same key as its shorthand", async () => {
    const onLinkClick = vi.fn();
    render(
      <MarkdownContent onLinkClick={onLinkClick}>{"See myc://decisions/db."}</MarkdownContent>,
    );

    await userEvent.click(screen.getByRole("button", { name: "decisions/db" }));

    expect(onLinkClick).toHaveBeenCalledWith("decisions/db");
  });

  it("shows a link's label instead of its key when one is given", () => {
    render(<MarkdownContent>{"[[decisions/db|why we chose it]]"}</MarkdownContent>);

    expect(screen.getByText("why we chose it")).toBeInTheDocument();
  });

  it("keeps a broken link inert rather than offering a dead target", () => {
    const onLinkClick = vi.fn();
    render(
      <MarkdownContent onLinkClick={onLinkClick} brokenLinks={new Set(["gone"])}>
        {"See [[gone]]."}
      </MarkdownContent>,
    );

    expect(screen.queryByRole("button", { name: /gone/ })).not.toBeInTheDocument();
    expect(screen.getByTitle("gone — no such memory")).toBeInTheDocument();
  });

  it("renders links inert when no click handler is supplied", () => {
    render(<MarkdownContent>{"See [[decisions/db]]."}</MarkdownContent>);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("decisions/db")).toBeInTheDocument();
  });

  it("leaves the agent skill's [[mycelium: …]] directive as plain text", () => {
    render(<MarkdownContent>{"[[mycelium: confidence=0.85 stance=accept]]"}</MarkdownContent>);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/confidence=0.85/)).toBeInTheDocument();
  });

  it("still highlights @mentions alongside links", () => {
    render(<MarkdownContent>{"@alice owns [[work/api]]"}</MarkdownContent>);

    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("work/api")).toBeInTheDocument();
  });

  it("makes a markdown link with a myc:// href navigable", async () => {
    const onLinkClick = vi.fn();
    render(
      <MarkdownContent onLinkClick={onLinkClick}>
        {"See [the call](myc://decisions/db)."}
      </MarkdownContent>,
    );

    await userEvent.click(screen.getByRole("button", { name: "the call" }));

    expect(onLinkClick).toHaveBeenCalledWith("decisions/db");
  });

  it("leaves an ordinary http link alone", () => {
    render(<MarkdownContent>{"See [the docs](https://example.com)."}</MarkdownContent>);

    expect(screen.getByRole("link", { name: "the docs" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
  });

  it("marks a transclusion distinctly from a plain link", () => {
    const onLinkClick = vi.fn();
    render(<MarkdownContent onLinkClick={onLinkClick}>{"![[glossary/slim]]"}</MarkdownContent>);

    expect(screen.getByTitle("Embeds glossary/slim")).toBeInTheDocument();
  });
});
