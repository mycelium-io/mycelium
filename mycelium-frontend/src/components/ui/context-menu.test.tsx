// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "./context-menu";

function Row({ onRename = () => {} }: { onRename?: () => void }) {
  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <div data-testid="row">checkout</div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem onClick={onRename}>Rename</ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

describe("<ContextMenu />", () => {
  afterEach(() => window.getSelection()?.removeAllRanges());

  it("opens on right-click and runs the item picked", async () => {
    const onRename = vi.fn();
    render(<Row onRename={onRename} />);
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();

    fireEvent.contextMenu(screen.getByTestId("row"), { clientX: 10, clientY: 10 });
    fireEvent.click(await screen.findByText("Rename"));
    expect(onRename).toHaveBeenCalledOnce();
  });

  it("renders its row in place, adding no element around it", () => {
    const { container } = render(<Row />);
    expect(container.firstElementChild).toBe(screen.getByTestId("row"));
  });

  function select(el: HTMLElement) {
    const range = document.createRange();
    range.selectNodeContents(el);
    window.getSelection()?.addRange(range);
  }

  it("leaves the browser's own menu to text selected inside the row", async () => {
    render(<Row />);
    const row = screen.getByTestId("row");
    select(row);

    fireEvent.mouseDown(row, { button: 2 });
    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });
    await waitFor(() => expect(screen.queryByText("Rename")).not.toBeInTheDocument());
  });

  it("opens on a right-click on a word, which a Mac selects as the click lands", async () => {
    render(<Row />);
    const row = screen.getByTestId("row");
    // Nothing selected when the button goes down; the press selects the word.
    fireEvent.mouseDown(row, { button: 2 });
    select(row);
    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });

    expect(await screen.findByText("Rename")).toBeInTheDocument();
    expect(window.getSelection()?.isCollapsed ?? true).toBe(true);
  });

  it("opens on a Ctrl-click on a word the same way", async () => {
    render(<Row />);
    const row = screen.getByTestId("row");
    fireEvent.mouseDown(row, { button: 0, ctrlKey: true });
    select(row);
    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });
    expect(await screen.findByText("Rename")).toBeInTheDocument();
  });
});
