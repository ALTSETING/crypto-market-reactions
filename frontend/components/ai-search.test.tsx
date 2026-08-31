import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiResult, AiSearch } from "@/components/ai-search";
import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { MockGeneralAnswerProvider } from "@/lib/ai-search/general-provider";
import { MockAiIntentProvider } from "@/lib/ai-search/provider";
import { MockAiResearchRouter } from "@/lib/ai-search/router";
import { executeAiSearch } from "@/lib/ai-search/service";
import type { AiGeneralSuccess } from "@/types/ai-search";

describe("AI Search prototype", () => {
  it("renders examples, states baseline, Reaction V2 provenance, and disclaimer context", () => {
    const html = renderToStaticMarkup(<AiSearch />);
    expect(html).toContain("Ask a question");
    expect(html).toContain("Based on Reaction V2");
    expect(html).toContain("How does ETH react to large institutional purchases?");
    expect(html).toContain("How does ETH react to sales by large investors?");
    expect(html).toContain("How does BTC react to ETF inflows?");
    expect(html).toContain("How does SOL react to large purchases?");
    expect(html).toContain("What is a Bitcoin ETF?");
    expect(html).toContain("Why can ETF outflows affect Bitcoin?");
    expect(html).toContain("Why can ETF outflows hurt Bitcoin, and what happened historically?");
    expect(html).toContain("Що таке стейкінг?");
    expect(html).toContain("Ask a specific historical question");
    expect(html).toContain("maxLength=\"500\"");
    expect(html).toContain("sm:flex-row");
    expect(html).toContain("min-w-0");
    expect(html).not.toContain("?question=");
  });

  it("renders the no-live-sources general mode without Reaction V2 claims", () => {
    const data: AiGeneralSuccess = {
      status: "ok",
      mode: "general",
      modeLabel: "General AI explanation — no live sources",
      language: "uk",
      answer: "Стейкінг підтримує роботу proof-of-stake мережі.",
      citations: [],
      disclaimer: "Загальне освітнє пояснення — не фінансова порада.",
    };
    const html = renderToStaticMarkup(<AiResult data={data} />);
    expect(html).toContain("General AI explanation — no live sources");
    expect(html).toContain("General explanation");
    expect(html).not.toContain("Reaction V2");
  });

  it("renders hybrid output as two clearly separated sections", async () => {
    const result = await executeAiSearch(
      "What are ETF inflows, and how does BTC react to them historically?",
      new MockAiIntentProvider(),
      new FixtureAiSearchDataAdapter(),
      new MockAiResearchRouter(),
      new MockGeneralAnswerProvider(),
    );
    expect(result.statusCode).toBe(200);
    if (result.statusCode !== 200) return;
    const html = renderToStaticMarkup(<AiResult data={result.body} />);
    expect(html).toContain("Combined answer: general explanation + Reaction V2");
    expect(html).toContain('aria-label="General explanation"');
    expect(html).toContain('aria-label="Historical evidence"');
    expect(html).toContain("Historical evidence");
    expect(html).toContain("Reaction V2");
  });
});
