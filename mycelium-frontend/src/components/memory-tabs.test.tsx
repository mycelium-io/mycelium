import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryTabs, memoryTabLabel } from "./memory-tabs";

describe("MemoryTabs", () => {
  it("names a memory by the last part of its key", () => {
    expect(memoryTabLabel("decisions/cutover")).toBe("cutover");
    expect(memoryTabLabel("readme")).toBe("readme");
  });

  it("opens, closes, and closes on a middle click", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <MemoryTabs
        keys={["decisions/cutover", "context/goal"]}
        active="context/goal"
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    const [cutover, goal] = screen.getAllByRole("tab");
    expect(goal).toHaveAttribute("aria-selected", "true");
    expect(cutover).toHaveAttribute("title", "decisions/cutover");

    fireEvent.click(screen.getByText("cutover"));
    expect(onSelect).toHaveBeenCalledWith("decisions/cutover");

    fireEvent.click(screen.getByRole("button", { name: "Close context/goal" }));
    expect(onClose).toHaveBeenCalledWith("context/goal");

    fireEvent.mouseDown(cutover, { button: 1 });
    expect(onClose).toHaveBeenCalledWith("decisions/cutover");
  });
});
