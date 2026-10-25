import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MarkdownContent } from "@/components/markdown-content";
import { tableToMarkdown } from "@/components/markdown-table";

const TABLE = ["| Option | Change | Lines |", "| :--- | --- | ---: |", "| A | Integer cents | 15 |", "| B | Round \\| each share | 4 |"].join("\n");

describe("a Markdown table", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sits in its frame, keeping each column's alignment", () => {
    const { container } = render(<MarkdownContent>{TABLE}</MarkdownContent>);
    const table = screen.getByRole("table");
    expect(table.closest(".md-table-frame")).not.toBeNull();
    const heads = within(table).getAllByRole("columnheader");
    expect(heads.map((h) => h.textContent)).toEqual(["Option", "Change", "Lines"]);
    expect(heads[0].style.textAlign).toBe("left");
    expect(heads[1].style.textAlign).toBe("");
    expect(within(table).getByText("15").style.textAlign).toBe("right");
    expect(container.querySelector(".md-table-copy")).not.toBeNull();
  });

  it("copies back as the Markdown it came from", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<MarkdownContent>{TABLE}</MarkdownContent>);
    expect(tableToMarkdown(screen.getByRole("table"))).toBe(
      ["| Option | Change | Lines |", "| :--- | --- | ---: |", "| A | Integer cents | 15 |", "| B | Round \\| each share | 4 |"].join("\n"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy table as Markdown" }));
    expect(writeText).toHaveBeenCalledWith(tableToMarkdown(screen.getByRole("table")));
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy table as Markdown" })).toHaveTextContent("Copied"));
  });
});
