import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiSearch } from "@/components/ai-search";

describe("AI Search prototype", () => {
  it("renders examples, states baseline, Reaction V2 provenance, and disclaimer context", () => {
    const html = renderToStaticMarkup(<AiSearch />);
    expect(html).toContain("AI Search");
    expect(html).toContain("Based on Reaction V2");
    expect(html).toContain("How did ETH react");
    expect(html).toContain("Ask a specific historical question");
    expect(html).toContain("maxLength=\"500\"");
  });
});
