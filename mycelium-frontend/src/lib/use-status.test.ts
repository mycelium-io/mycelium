import { describe, expect, it } from "vitest";

import { isOpenWork } from "./use-status";

describe("isOpenWork", () => {
  it("counts a work row that is still open", () => {
    expect(isOpenWork({ key: "work/fix", meta: { status: "open" } })).toBe(true);
    expect(isOpenWork({ key: "work/fix", meta: { assignment: "held" } })).toBe(true);
  });

  it("does not count a row the board resolved, whatever its status says", () => {
    // `board resolve` writes the assignment and leaves status as it was.
    expect(isOpenWork({ key: "work/fix", meta: { status: "open", assignment: "resolved" } })).toBe(
      false,
    );
    expect(isOpenWork({ key: "work/fix", meta: { status: "dismissed" } })).toBe(false);
  });

  it("counts only work rows", () => {
    expect(isOpenWork({ key: "decisions/api", meta: { status: "open" } })).toBe(false);
  });
});
