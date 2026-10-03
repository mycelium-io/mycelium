import { describe, expect, it } from "vitest";
import { typeset } from "./typeset";

describe("typeset", () => {
  it("curls apostrophes and quotes", () => {
    expect(typeset(`it's the "support first" path`)).toBe("it’s the “support first” path");
    expect(typeset(`I'd go with 'option 1'.`)).toBe("I’d go with ‘option 1’.");
  });

  it("closes a quote that starts a run with nothing after it, as after bold", () => {
    // **mostly**" done → the run after the bold starts with the closing mark
    expect(typeset(`" done`)).toBe("” done");
    expect(typeset(`"done"`)).toBe("“done”");
  });

  it("opens a quote after a bracket or a dash", () => {
    expect(typeset(`("quoted")`)).toBe("(“quoted”)");
  });

  it("draws three periods as an ellipsis, and leaves four alone", () => {
    expect(typeset("wait...")).toBe("wait…");
    expect(typeset("a....b")).toBe("a....b");
  });

  it("leaves text with no marks as it was", () => {
    expect(typeset("ship it -- today")).toBe("ship it -- today");
  });
});
