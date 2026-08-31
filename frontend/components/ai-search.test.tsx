import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiSearch } from "@/components/ai-search";

describe("AI Search prototype", () => {
  it("renders examples, states baseline, Reaction V2 provenance, and disclaimer context", () => {
    const html = renderToStaticMarkup(<AiSearch />);
    expect(html).toContain("Ask a question");
    expect(html).toContain("Based on Reaction V2");
    expect(html).toContain("How does ETH react to large institutional purchases?");
    expect(html).toContain("How does ETH react to sales by large investors?");
    expect(html).toContain("How does BTC react to ETF inflows?");
    expect(html).toContain("How does SOL react to large purchases?");
    expect(html).toContain("Ask a specific historical question");
    expect(html).toContain("maxLength=\"500\"");
  });
});
