import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { StrayDropGuard } from "./stray-drop-guard";

/** A drag event as the browser sends it, carrying `types`. jsdom has no DragEvent. */
function drag(type: "dragover" | "drop", types: string[]) {
  const e = new Event(type, { bubbles: true, cancelable: true }) as Event & { dataTransfer: unknown };
  const dataTransfer = { types, dropEffect: "copy" };
  Object.defineProperty(e, "dataTransfer", { value: dataTransfer });
  return { e, dataTransfer };
}

describe("a file dropped outside a drop target", () => {
  it("is refused, so the app isn't replaced by the file", () => {
    render(<StrayDropGuard />);
    const over = drag("dragover", ["Files"]);
    document.body.dispatchEvent(over.e);
    expect(over.e.defaultPrevented).toBe(true);
    expect(over.dataTransfer.dropEffect).toBe("none");
    const dropped = drag("drop", ["Files"]);
    document.body.dispatchEvent(dropped.e);
    expect(dropped.e.defaultPrevented).toBe(true);
  });

  it("leaves a drop target's own drop alone", () => {
    render(<StrayDropGuard />);
    const target = document.createElement("div");
    document.body.appendChild(target);
    target.addEventListener("dragover", (e) => {
      e.preventDefault();
      (e as Event & { dataTransfer: { dropEffect: string } }).dataTransfer.dropEffect = "copy";
    });
    const over = drag("dragover", ["Files"]);
    target.dispatchEvent(over.e);
    expect(over.dataTransfer.dropEffect).toBe("copy");
    target.remove();
  });

  it("ignores a drag that carries no files, such as a card or a room", () => {
    render(<StrayDropGuard />);
    const over = drag("dragover", ["text/plain"]);
    document.body.dispatchEvent(over.e);
    expect(over.e.defaultPrevented).toBe(false);
  });
});
