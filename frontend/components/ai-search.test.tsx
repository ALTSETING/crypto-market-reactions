import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AiLoadingState, AiMessage, AiResult, AiSearch } from "@/components/ai-search";
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
    expect(html).toContain("<textarea");
    expect(html).toContain("Shift + Enter");
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

  it("renders historical unavailability without adding an evidence surface", () => {
    const data: AiAgentSuccess = {
      status: "ok",
      mode: "agent",
      modeLabel: "AI explanation",
      language: "en",
      answer: "A general explanation remains available.",
      historical: null,
      historicalUnavailable: true,
      historicalMessage: "Historical evidence is temporarily unavailable.",
      citations: [],
      disclaimer: "Educational answer — not financial advice.",
    };
    const html = renderToStaticMarkup(<AiResult data={data} />);
    expect(html).toContain("Historical evidence unavailable");
    expect(html).toContain('role="status"');
    expect(html).not.toContain('aria-label="Historical evidence"');
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
    expect(html).toContain(">Historical evidence<");
    expect(html).toContain(">Reaction V2<");
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
      expect(tableHtml).toContain("<table");
      expect(tableHtml).toContain('scope="col"');
      expect(tableHtml).toContain('scope="row"');
      expect(tableHtml).toContain("Historical Reaction V2 returns by horizon");
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

    if (ranking.body.mode === "agent" && ranking.body.historical) {
      const populatedRanking: AiAgentSuccess = {
        ...ranking.body,
        historical: {
          ...ranking.body.historical,
          answer: "Ranked from deterministic Reaction V2 observations.",
          calculation: "Eligible topics use the configured minimum independent sample.",
          result: {
            kind: "topic_ranking",
            metric: "positive_share",
            order: "highest",
            horizon: "24h",
            minimumSampleSize: 10,
            eligibleTopicCount: 1,
            insufficientData: false,
            items: [{ topic: "etf_approval", value: 62.5, independentSampleSize: 16, positive95Ci: { low: 38.6, high: 81.5 } }],
            citations: [],
          },
        },
      };
      const populatedHtml = renderToStaticMarkup(<AiResult data={populatedRanking} />);
      expect(populatedHtml).toContain("1. ETF approvals");
      expect(populatedHtml).toContain("independent N 16");
    }
  });

  it("keeps loading, warning, and error feedback lightweight and accessible", () => {
    const loadingHtml = renderToStaticMarkup(<AiLoadingState />);
    const warningHtml = renderToStaticMarkup(<AiMessage kind="warning" label="Historical evidence unavailable" message="Try again later." />);
    const errorHtml = renderToStaticMarkup(<AiMessage kind="error" label="Unable to complete request" message="Provider unavailable." />);
    expect(loadingHtml).toContain('role="status"');
    expect(loadingHtml).toContain("Reviewing the question");
    expect(warningHtml).toContain('role="status"');
    expect(errorHtml).toContain('role="alert"');
    expect(errorHtml).not.toContain("rounded-2xl border");
  });

  it("wraps long prose and a citation list with more than twenty sources", async () => {
    const result = await executeAiAgentResearch(
      "What are ETF inflows, and how does BTC react to them historically?",
      new MockAiResearchAgent(),
      new FixtureAiSearchDataAdapter(),
    );
    expect(result.statusCode).toBe(200);
    if (result.statusCode !== 200 || result.body.mode !== "agent" || !result.body.historical) return;
    const citations = Array.from({ length: 21 }, (_, index) => ({
      eventId: `long-source-${index}`,
      href: `/events/long-source-${index}`,
      title: `${index + 1}. Extremely long historical source title about institutional crypto market flows that must wrap without widening the viewport ${"context ".repeat(8)}`,
    }));
    const data: AiAgentSuccess = {
      ...result.body,
      answer: `Довга українська відповідь має залишатися читабельною на вузькому екрані. ${"Пояснення ринкового контексту. ".repeat(20)}`,
      historical: { ...result.body.historical, citations },
    };
    const html = renderToStaticMarkup(<AiResult data={data} />);
    expect(html).toContain("Sources · 21");
    expect(html.match(/href="\/events\/long-source-/gu)).toHaveLength(21);
    expect(html).toContain("max-w-[800px]");
    expect(html).toContain("overflow-wrap:anywhere");
  });
});
