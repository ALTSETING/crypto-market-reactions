import { describe, expect, it } from "vitest";

import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { createHistoricalToolExecutor, MockAiResearchAgent } from "@/lib/ai-search/agent";
import { executeAiAgentResearch } from "@/lib/ai-search/service";
import type { AiTopic, HistoricalOperation } from "@/types/ai-search";
import type { Asset, Horizon } from "@/types/events";

interface Expected {
  question: string;
  operation: HistoricalOperation;
  kind: string;
  asset: Asset;
  topic: AiTopic | null;
  horizon: Horizon | null;
  dateFrom?: string;
  dateTo?: string;
}

const cases: Expected[] = [
  { question: "На які новини ETH найчастіше реагував зростанням?", operation: "topic_ranking", kind: "topic_ranking", asset: "ETH", topic: null, horizon: "24h" },
  { question: "На які новини ETH найчастіше реагував зростанням за 24h?", operation: "topic_ranking", kind: "topic_ranking", asset: "ETH", topic: null, horizon: "24h" },
  { question: "What type of news most often led to BTC gains?", operation: "topic_ranking", kind: "topic_ranking", asset: "BTC", topic: null, horizon: "24h" },
  { question: "Which events produced the biggest SOL losses at 1h?", operation: "top_losers", kind: "ranking", asset: "SOL", topic: null, horizon: "1h" },
  { question: "Count ETH hacks in 2023", operation: "count", kind: "count", asset: "ETH", topic: "hack", horizon: null, dateFrom: "2023-01-01", dateTo: "2023-12-31" },
  { question: "Find BTC ETF events in 2024", operation: "search", kind: "search", asset: "BTC", topic: "etf", horizon: null, dateFrom: "2024-01-01", dateTo: "2024-12-31" },
  { question: "Top 3 SOL losses after hacks at 1h", operation: "top_losers", kind: "ranking", asset: "SOL", topic: "hack", horizon: "1h" },
  { question: "ETF approvals or institutional purchases — which had a stronger ETH 24h reaction?", operation: "topic_comparison", kind: "topic_comparison", asset: "ETH", topic: null, horizon: "24h" },
  { question: "Як eth реагує коли вливаються великі гроші?", operation: "overview", kind: "multi_horizon", asset: "ETH", topic: "institutional_purchase", horizon: null },
  { question: "What happens btc when money leaves etfs", operation: "overview", kind: "multi_horizon", asset: "BTC", topic: "etf_outflow", horizon: null },
];

describe("historical operation grounding regression", () => {
  it.each(cases)("grounds $operation for $question", async (expected) => {
    const response = await executeAiAgentResearch(expected.question, new MockAiResearchAgent(), new FixtureAiSearchDataAdapter());
    expect(response.statusCode).toBe(200);
    if (response.statusCode !== 200 || response.body.mode !== "agent") return;
    expect(response.body.historical).not.toBeNull();
    expect(response.body.historical?.operation).toBe(expected.operation);
    expect(response.body.historical?.result.kind).toBe(expected.kind);
    expect(response.body.historical?.intent).toMatchObject({
      asset: expected.asset,
      topic: expected.topic,
      horizon: expected.horizon,
      ...(expected.dateFrom ? { dateFrom: expected.dateFrom } : {}),
      ...(expected.dateTo ? { dateTo: expected.dateTo } : {}),
    });
  });

  it("returns insufficient data instead of inventing a topic winner below the independent-sample minimum", async () => {
    const response = await executeAiAgentResearch(cases[0].question, new MockAiResearchAgent(), new FixtureAiSearchDataAdapter());
    expect(response.statusCode).toBe(200);
    if (response.statusCode !== 200 || response.body.mode !== "agent") return;
    expect(response.body.historical?.result).toMatchObject({
      kind: "topic_ranking",
      minimumSampleSize: 10,
      insufficientData: true,
      items: [],
    });
    expect(response.body.historical?.answer).toMatch(/Insufficient data/);
  });

  it("keeps imperfect Ukrainian institutional-purchase grounding", async () => {
    const question = "Як ETH реагував на великі інституційні покупки?";
    const execute = createHistoricalToolExecutor(question, new FixtureAiSearchDataAdapter());
    let captured: unknown;
    const result = await new MockAiResearchAgent().run(question, async (argumentsValue) => {
      captured = { argumentsValue, outcome: await execute(argumentsValue) };
      return (captured as { outcome: Awaited<ReturnType<typeof execute>> }).outcome;
    });
    expect(captured).toMatchObject({ outcome: { ok: true } });
    expect(result.historical).not.toBeNull();
  });
});
