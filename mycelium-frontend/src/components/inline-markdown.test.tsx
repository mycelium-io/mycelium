// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InlineMarkdown } from "./inline-markdown";

const html = (text: string) => render(<InlineMarkdown text={text} />).container.innerHTML;

describe("inline markdown", () => {
  it("reads bold, italic and code", () => {
    const out = html("**38%** free, *swap* in `vm_stat`");
    expect(out).toContain("<strong");
    expect(out).toContain(">38%</strong>");
    expect(out).toContain("<em>swap</em>");
    expect(out).toContain(">vm_stat</code>");
  });

  it("reads italic inside bold", () => {
    expect(html("**very *much* so**")).toMatch(/<strong[^>]*>very <em>much<\/em> so<\/strong>/);
  });

  it("leaves everything else as the characters written", () => {
    const out = html("# up [docs](https://example.com) <b>x</b> 2 * 3 * 4");
    expect(out).not.toContain("<a");
    expect(out).not.toContain("<b>");
    expect(out).not.toContain("<em>");
    expect(out).toContain("# up [docs](https://example.com) &lt;b&gt;x&lt;/b&gt; 2 * 3 * 4");
  });
});
