import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiResult, AiSearch } from "@/components/ai-search";
import { MockAiResearchAgent } from "@/lib/ai-search/agent";
import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { executeAiAgentResearch } from "@/lib/ai-search/service";
import type { AiAgentSuccess } from "@/types/ai-search";

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
    expect(html).toContain("Ask any crypto research question");
    expect(html).toContain("maxLength=\"500\"");
    expect(html).toContain("sm:flex-row");
    expect(html).toContain("min-w-0");
    expect(html).not.toContain("?question=");
  });

  it("renders a conversational general answer without historical claims", () => {
    const data: AiAgentSuccess = {
      status: "ok",
      mode: "agent",
      modeLabel: "AI explanation",
      language: "uk",
      answer: "Стейкінг підтримує роботу proof-of-stake мережі.",
      historical: null,
      historicalUnavailable: false,
      historicalMessage: null,
      citations: [],
      disclaimer: "Загальне освітнє пояснення — не фінансова порада.",
    };
    const html = renderToStaticMarkup(<AiResult data={data} />);
    expect(html).toContain("AI explanation");
    expect(html).not.toContain("Reaction V2");
  });

  it("renders agent explanation and deterministic historical evidence as separate sections", async () => {
    const result = await executeAiAgentResearch(
      "What are ETF inflows, and how does BTC react to them historically?",
      new MockAiResearchAgent(),
      new FixtureAiSearchDataAdapter(),
    );
    expect(result.statusCode).toBe(200);
    if (result.statusCode !== 200) return;
    const html = renderToStaticMarkup(<AiResult data={result.body} />);
    expect(html).toContain("AI explanation");
    expect(html).toContain('aria-label="AI explanation"');
    expect(html).toContain('aria-label="Historical evidence"');
    expect(html).toContain("Historical evidence — Reaction V2");
    expect(html).toContain("Reaction V2");
    expect(html).toContain("Matched articles");
    expect(html).toContain("Independent events");
    expect(html).toContain("overflow-wrap:anywhere");

    const tableResult = await executeAiAgentResearch(
      "How did SOL react historically?",
      new MockAiResearchAgent(),
      new FixtureAiSearchDataAdapter(),
    );
    expect(tableResult.statusCode).toBe(200);
    if (tableResult.statusCode === 200) {
      const tableHtml = renderToStaticMarkup(<AiResult data={tableResult.body} />);
      expect(tableHtml).toContain('data-testid="historical-table-scroll"');
      expect(tableHtml).toContain("overflow-x-auto");
    }
  });

  it("renders deterministic topic ranking insufficiency and topic comparison without model-authored values", async () => {
    const ranking = await executeAiAgentResearch(
      "На які новини ETH найчастіше реагував зростанням за 24h?",
      new MockAiResearchAgent(),
      new FixtureAiSearchDataAdapter(),
    );
    expect(ranking.statusCode).toBe(200);
    if (ranking.statusCode !== 200) return;
    const rankingHtml = renderToStaticMarkup(<AiResult data={ranking.body} />);
    expect(rankingHtml).toContain("Insufficient data for a reliable topic ranking");
    expect(rankingHtml).toContain("minimum of 10 independent Reaction V2 observations");

    const comparison = await executeAiAgentResearch(
      "ETF approvals or institutional purchases — which had a stronger ETH 24h reaction?",
      new MockAiResearchAgent(),
      new FixtureAiSearchDataAdapter(),
    );
    expect(comparison.statusCode).toBe(200);
    if (comparison.statusCode !== 200) return;
    const comparisonHtml = renderToStaticMarkup(<AiResult data={comparison.body} />);
    expect(comparisonHtml).toContain("Topic comparison");
    expect(comparisonHtml).toContain("ETF approvals");
    expect(comparisonHtml).toContain("Institutional purchases");
  });
});
