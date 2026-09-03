import { describe, expect, it } from "vitest";

import { runMultiHorizonAnalytics } from "@/lib/ai-search/analytics";
import { ApiV1ReactionService } from "@/lib/api-v1/data";
import type { AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import type { AiSearchIntent, AnalyticsEvent, AnalyticsResult, MultiHorizonAnalyticsResult } from "@/types/ai-search";
import { ASSETS, HORIZONS } from "@/types/events";

function event(id: string, title: string, sourceClass: AnalyticsEvent["sourceClass"], value: number | null): AnalyticsEvent {
  const reactionV2 = Object.fromEntries(ASSETS.map((asset) => [
    asset,
    Object.fromEntries(HORIZONS.map((horizon) => [horizon, asset === "BTC" ? value : null])),
  ])) as AnalyticsEvent["reactionV2"];
  return {
    eventId: id,
    slug: id,
    title,
    publishedAt: `2025-01-01T1${id === "first" ? "0" : "1"}:00:00.000Z`,
    assets: ["BTC"],
    primaryAsset: "BTC",
    category: "etf",
    sourceClass,
    sentiment: null,
    importance: null,
    reactionV2,
  };
}

class LocalPipelineAdapter implements AiSearchDataAdapter {
  lastOverviewIntent: AiSearchIntent | null = null;

  constructor(private readonly events: AnalyticsEvent[]) {}
  async analyze(): Promise<AnalyticsResult> {
    throw new Error("Not used by API V1 reaction summaries");
  }
  async analyzeOverview(intent: AiSearchIntent): Promise<MultiHorizonAnalyticsResult> {
    this.lastOverviewIntent = intent;
    return runMultiHorizonAnalytics(this.events, intent);
  }
}

describe("API V1 Reaction V2 consistency", () => {
  it("uses Topic Matching V2 and Dedup V3 sample sizes without recalculating reactions", async () => {
    const adapter = new LocalPipelineAdapter([
      event("first", "BlackRock Bitcoin ETF records $100m outflows", "primary_document", -1),
      event("second", "BlackRock Bitcoin ETF reports $100m outflows", "news_media", -2),
    ]);
    const service = new ApiV1ReactionService(adapter);
    const [row] = await service.query({ asset: "BTC", topic: "etf_outflow", horizon: "24h", dateFrom: null, dateTo: null, direction: null });
    expect(adapter.lastOverviewIntent).toMatchObject({ asset: "BTC", horizon: "24h", topic: "etf_outflow" });
    expect(row).toMatchObject({
      matchedArticles: 2,
      independentEvents: 1,
      sampleSize: 1,
      mean: -1,
      median: -1,
      positivePercent: 0,
      negativePercent: 100,
    });
  });

  it("keeps a fully missing Reaction V2 sample null", async () => {
    const service = new ApiV1ReactionService(new LocalPipelineAdapter([
      event("first", "BlackRock Bitcoin ETF records $100m outflows", "primary_document", null),
    ]));
    const [row] = await service.query({ asset: "BTC", topic: "etf_outflow", horizon: "1m", dateFrom: null, dateTo: null, direction: null });
    expect(row).toMatchObject({ matchedArticles: 1, independentEvents: 0, sampleSize: 0, mean: null, median: null, positivePercent: null, negativePercent: null });
  });
});
