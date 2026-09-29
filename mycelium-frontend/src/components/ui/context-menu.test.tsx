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

  it("leaves the browser's own menu to text selected inside the row", async () => {
    render(<Row />);
    const row = screen.getByTestId("row");
    const range = document.createRange();
    range.selectNodeContents(row);
    window.getSelection()?.addRange(range);

    fireEvent.contextMenu(row, { clientX: 10, clientY: 10 });
    await waitFor(() => expect(screen.queryByText("Rename")).not.toBeInTheDocument());
  });
});
