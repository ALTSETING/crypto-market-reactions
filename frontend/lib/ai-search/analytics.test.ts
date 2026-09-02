import { describe, expect, it } from "vitest";

import { runAnalytics, runTopicComparisonAnalytics, runTopicRankingAnalytics } from "@/lib/ai-search/analytics";
import { AI_SEARCH_FIXTURES } from "@/lib/ai-search/fixtures";
import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, AnalyticsEvent } from "@/types/ai-search";
import { HORIZONS, type Asset, type Horizon } from "@/types/events";

const base: AiSearchIntent = {
  intent: "aggregate", asset: "ETH", dateFrom: "2024-01-01", dateTo: "2024-12-31",
  category: "regulation", topic: null, actorType: "unknown", action: null, direction: "unknown",
  magnitude: "unknown", amount: null, entity: null, assetRole: "any", sourceClass: "primary_document", sentiment: null,
  reactionSign: null, importance: null,
  horizon: "24h", metric: "mean", sort: "newest", groupBy: "none", comparison: null, limit: 50,
};

function topicEvents(topic: "hack" | "staking", count: number, positives: number): AnalyticsEvent[] {
  return Array.from({ length: count }, (_, index) => {
    const reactionV2 = Object.fromEntries((["BTC", "ETH", "SOL"] as Asset[]).map((asset) => [
      asset,
      Object.fromEntries(HORIZONS.map((horizon) => [horizon, null])) as Record<Horizon, number | null>,
    ])) as AnalyticsEvent["reactionV2"];
    reactionV2.ETH["24h"] = index < positives ? 1 : -1;
    return {
      eventId: `${topic}-${index}`,
      slug: `${topic}-${index}`,
      title: topic === "hack" ? `Ethereum Protocol${index} hack exploit incident` : `Validator${index} Ethereum staking announcement`,
      publishedAt: new Date(Date.UTC(2020, 0, 1 + index * 32)).toISOString(),
      assets: ["ETH"],
      primaryAsset: "ETH",
      category: topic === "hack" ? "security_event" : "staking",
      sourceClass: "official_announcement",
      sentiment: null,
      importance: null,
      reactionV2,
    };
  });
}

describe("deterministic Reaction V2 analytics", () => {
  it("calculates mean and excludes nulls rather than replacing them with zero", () => {
    expect(runAnalytics(AI_SEARCH_FIXTURES, base)).toMatchObject({ kind: "scalar", value: 1.4, sampleSize: 2 });
    expect(runAnalytics(AI_SEARCH_FIXTURES, { ...base, category: "etf", sourceClass: "news_media" })).toMatchObject({ kind: "scalar", value: null, sampleSize: 0 });
  });

  it("calculates median and sign shares exactly", () => {
    expect(runAnalytics(AI_SEARCH_FIXTURES, { ...base, metric: "median" })).toMatchObject({ value: 1.4, sampleSize: 2 });
    expect(runAnalytics(AI_SEARCH_FIXTURES, { ...base, category: null, sourceClass: null, metric: "sign_share" })).toMatchObject({ positivePercent: 50, negativePercent: 50, neutralPercent: 0, sampleSize: 2 });
  });

  it("ranks deterministically and caps citations", () => {
    const result = runAnalytics(AI_SEARCH_FIXTURES, { ...base, intent: "rank", asset: "SOL", category: null, sourceClass: null, horizon: "1h", metric: "reaction", sort: "losers", limit: 2 });
    expect(result).toMatchObject({ kind: "ranking", sampleSize: 3 });
    if (result.kind !== "ranking") throw new Error("Expected ranking result");
    expect(result.items[0]).toMatchObject({ eventId: "evt-ai-005", reaction: -7.8 });
    expect(result.citations).toHaveLength(2);
  });

  it("compares groups and reports each sample size", () => {
    const result = runAnalytics(AI_SEARCH_FIXTURES, { ...base, intent: "compare", asset: "BTC", category: null, sourceClass: null, horizon: "4h", metric: "mean", groupBy: "source_class", comparison: { field: "sourceClass", left: "primary_document", right: "news_media" } });
    expect(result).toMatchObject({ kind: "comparison", left: { value: 2.35, sampleSize: 2 }, right: { value: 2.2, sampleSize: 1 }, difference: 0.15 });
  });

  it("rejects invalid enums, extra fields, dates, and limits", () => {
    expect(() => validateIntent({ ...base, asset: "DOGE" })).toThrow();
    expect(() => validateIntent({ ...base, limit: 51 })).toThrow();
    expect(() => validateIntent({ ...base, dateFrom: "2024-13-01" })).toThrow();
    expect(() => validateIntent({ ...base, dateFrom: "2024-02-31" })).toThrow();
    expect(() => validateIntent({ ...base, sql: "select 1" })).toThrow();
  });

  it("produces byte-identical repeated output", () => {
    expect(JSON.stringify(runAnalytics(AI_SEARCH_FIXTURES, base))).toBe(JSON.stringify(runAnalytics(AI_SEARCH_FIXTURES, base)));
  });

  it("requires ten independent observations and uses Wilson lower-bound then sample size for positive-share topic ties", () => {
    const intent = { ...base, dateFrom: null, dateTo: null, category: null, sourceClass: null, topic: null };
    const result = runTopicRankingAnalytics(
      [...topicEvents("hack", 10, 8), ...topicEvents("staking", 20, 16)],
      intent,
      "positive_share",
      "highest",
      5,
    );
    expect(result).toMatchObject({ kind: "topic_ranking", minimumSampleSize: 10, insufficientData: false });
    expect(result.items[0]).toMatchObject({ topic: "staking", value: 80, independentSampleSize: 20 });
    expect(result.items.find(({ topic }) => topic === "hack")).toMatchObject({ value: 80, independentSampleSize: 10 });

    const insufficient = runTopicRankingAnalytics(topicEvents("hack", 9, 9), intent, "positive_share", "highest", 5);
    expect(insufficient).toMatchObject({ eligibleTopicCount: 0, insufficientData: true, items: [] });
  });

  it("compares two topics deterministically without model arithmetic", () => {
    const intent = { ...base, dateFrom: null, dateTo: null, category: null, sourceClass: null, topic: null };
    const result = runTopicComparisonAnalytics(
      [...topicEvents("hack", 10, 6), ...topicEvents("staking", 10, 8)],
      intent,
      "hack",
      "staking",
      "positive_share",
    );
    expect(result).toMatchObject({
      kind: "topic_comparison",
      left: { topic: "hack", value: 60, independentSampleSize: 10 },
      right: { topic: "staking", value: 80, independentSampleSize: 10 },
      difference: -20,
    });
  });
});
