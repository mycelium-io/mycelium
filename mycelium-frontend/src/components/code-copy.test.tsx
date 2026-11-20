import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MarkdownContent } from "@/components/markdown-content";

function clipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  return writeText;
}

describe("copying code in a message", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.getSelection()?.removeAllRanges();
  });

  it("copies a code block's text, without its trailing newline", async () => {
    const writeText = clipboard();
    render(<MarkdownContent>{"Start it:\n\n```bash\ncd backend\nuv run app\n```"}</MarkdownContent>);
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    expect(writeText).toHaveBeenCalledWith("cd backend\nuv run app");
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy code" })).toHaveTextContent("Copied"));
  });

  it("copies one code span on a click, and only that span", async () => {
    const writeText = clipboard();
    render(<MarkdownContent>{"Run `mycelium board new` and then `mycelium await`."}</MarkdownContent>);
    const code = screen.getByText("mycelium await");
    fireEvent.click(code);
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("mycelium await");
    await waitFor(() => expect(code).toHaveAttribute("data-copied"));
    expect(screen.getByText("mycelium board new")).not.toHaveAttribute("data-copied");
  });

  it("copies nothing when the click ends a text selection", () => {
    const writeText = clipboard();
    render(<MarkdownContent>{"Run `mycelium board new` now."}</MarkdownContent>);
    const code = screen.getByText("mycelium board new");
    const range = document.createRange();
    range.selectNodeContents(code);
    window.getSelection()?.addRange(range);
    fireEvent.click(code);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("leaves code in a link's text and in a one-line preview alone", () => {
    const writeText = clipboard();
    const { container } = render(<MarkdownContent>{"See [`the docs`](https://example.com)."}</MarkdownContent>);
    expect(container.querySelector(".md-code-inline")).toBeNull();
    render(<MarkdownContent inline>{"Run `mycelium await` first"}</MarkdownContent>);
    fireEvent.click(screen.getByText("mycelium await"));
    expect(writeText).not.toHaveBeenCalled();
  });
});
