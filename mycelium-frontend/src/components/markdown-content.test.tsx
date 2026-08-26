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
    expect(screen.getByText("gone")).toHaveAttribute("aria-description", "gone — no such memory");
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

    expect(screen.getByRole("button")).toHaveAttribute("aria-description", "Embeds glossary/slim");
  });

  it("renders a /skill reference as a chip that opens its skills/ memory", async () => {
    const onLinkClick = vi.fn();
    render(<MarkdownContent onLinkClick={onLinkClick}>{"run /demo-review now"}</MarkdownContent>);

    await userEvent.click(screen.getByRole("button", { name: "/demo-review" }));

    expect(onLinkClick).toHaveBeenCalledWith("skills/demo-review");
  });

  it("does not treat a slash inside a path or URL as a skill reference", () => {
    render(<MarkdownContent>{"see path/to/file and http://x.com/y"}</MarkdownContent>);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("leaves a wikilink/transclusion syntax example inside a code span inert", () => {
    // A glossary row like `` `![[key]]` embeds the target `` is prose *about*
    // the syntax, not a live link — it must not become a chip that navigates
    // to a literal memory named "key".
    render(
      <MarkdownContent onLinkClick={vi.fn()}>
        {"Transclusion: `![[key]]` embeds the target body, and `[[key]]` is a wikilink."}
      </MarkdownContent>,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/!\[\[key\]\]/)).toBeInTheDocument();
  });

  it("renders a single newline as a line break, not a collapsed space", () => {
    // Agents post terminal-style prose with single newlines. Without remark-breaks
    // CommonMark folds these into one paragraph and the message walls up; with it
    // each line breaks. One <p> that carries a <br> between the two lines.
    const { container } = render(<MarkdownContent>{"Line one.\nLine two."}</MarkdownContent>);

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(1);
    expect(paragraphs[0].querySelector("br")).toBeInTheDocument();
  });
});

describe("<MarkdownContent /> headings", () => {
  it("renders every heading level as a heading element", () => {
    // h5/h6 have no entry in the component map unless one is declared, and
    // Tailwind's preflight resets headings to body size and weight — so a level
    // that falls out of the map renders as prose with a heading role and no
    // visible difference from the paragraph above it.
    render(
      <MarkdownContent>
        {"# One\n\n## Two\n\n### Three\n\n#### Four\n\n##### Five\n\n###### Six"}
      </MarkdownContent>,
    );

    for (const [level, text] of [
      [1, "One"],
      [2, "Two"],
      [3, "Three"],
      [4, "Four"],
      [5, "Five"],
      [6, "Six"],
    ] as const) {
      expect(screen.getByRole("heading", { level, name: text })).toBeInTheDocument();
    }
  });

  it("processes mentions and memory links inside a heading", () => {
    const onLinkClick = vi.fn();
    render(
      <MarkdownContent onLinkClick={onLinkClick}>
        {"###### @alice on [[work/api]]"}
      </MarkdownContent>,
    );

    const heading = screen.getByRole("heading", { level: 6 });
    expect(heading).toContainElement(screen.getByText("@alice"));
    expect(heading).toContainElement(screen.getByRole("button", { name: /work\/api/ }));
  });
});
