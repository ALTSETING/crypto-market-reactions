import { describe, expect, it } from "vitest";

import { mean, median, runAnalytics, runMultiHorizonAnalytics } from "@/lib/ai-search/analytics";
import { formatPercent } from "@/lib/ai-search/format";
import { applyExplicitQuestionDefaults } from "@/lib/ai-search/intent-defaults";
import { MockAiIntentProvider } from "@/lib/ai-search/provider";
import { validateIntent } from "@/lib/ai-search/schema";
import { matchesTopic } from "@/lib/ai-search/topic-matcher";
import type { AiSearchIntent, AnalyticsEvent } from "@/types/ai-search";

const baseIntent: AiSearchIntent = {
  intent: "aggregate",
  asset: "ETH",
  dateFrom: null,
  dateTo: null,
  category: null,
  topic: null,
  sourceClass: null,
  sentiment: null,
  reactionSign: null,
  importance: null,
  horizon: "24h",
  metric: "mean",
  sort: "newest",
  groupBy: "none",
  comparison: null,
  limit: 50,
};

function event(id: string, title: string, reactions: Partial<AnalyticsEvent["reactionV2"]["ETH"]>): AnalyticsEvent {
  return {
    eventId: id,
    slug: id,
    title,
    publishedAt: `2024-01-${id.padStart(2, "0")}T00:00:00Z`,
    assets: ["ETH"],
    category: "news",
    sourceClass: "news_media",
    sentiment: null,
    importance: null,
    reactionV2: {
      BTC: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
      ETH: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null, ...reactions },
      SOL: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
    },
  };
}

describe("AI topic architecture", () => {
  it.each([
    ["How did ETH react to SEC filings in 2024 after 24h?", "sec_filings", null],
    ["How did ETH react to ETF news?", "etf", null],
    ["How did SOL react to hack news?", "hack", null],
    ["How did BTC react to CPI news?", "cpi", null],
    ["Як ETH реагує на великі фінансові інвестиції?", "large_investment", null],
  ] as const)("infers a precise topic for %s", async (question, topic, category) => {
    const resolution = await new MockAiIntentProvider().resolve(question);
    expect(resolution).toMatchObject({ status: "ready", intent: { topic, category } });
  });

  it("keeps editorial sentiment separate from Reaction V2 sign", async () => {
    const reactions = await new MockAiIntentProvider().resolve("How many positive ETH reactions were there in 2023?");
    expect(reactions).toMatchObject({
      status: "ready",
      intent: { sentiment: null, reactionSign: "positive", horizon: "24h", metric: "count" },
    });
    const sentiment = await new MockAiIntentProvider().resolve("Count ETH events with positive sentiment in 2023");
    expect(sentiment).toMatchObject({
      status: "ready",
      intent: { sentiment: "positive", reactionSign: null, horizon: null, metric: "count" },
    });
  });

  it("ignores a provider-invented horizon when the question asks for a general reaction", () => {
    const resolution = applyExplicitQuestionDefaults("How did ETH react to ETF news?", {
      status: "ready",
      intent: { ...baseIntent, topic: "etf", horizon: "24h" },
    });
    expect(resolution).toMatchObject({ status: "ready", intent: { topic: "etf", horizon: null } });
  });

  it("rejects arbitrary topic strings at the strict schema boundary", () => {
    expect(() => validateIntent({ ...baseIntent, topic: "anything-the-model-invented" })).toThrow(/allowlist/i);
  });

  it("matches only static server-side topic patterns", () => {
    expect(matchesTopic({ title: "Company files an SEC 10-Q registration statement" }, "sec_filings")).toBe(true);
    expect(matchesTopic({ title: "EU publishes generic crypto regulation proposal" }, "sec_filings")).toBe(false);
    expect(matchesTopic({ title: "Spot Ethereum ETF receives approval" }, "etf")).toBe(true);
    expect(matchesTopic({ title: "Ethereum protocol upgrade announced" }, "etf")).toBe(false);
    expect(matchesTopic({ title: "Solana bridge exploit drains funds" }, "hack")).toBe(true);
    expect(matchesTopic({ title: "Solana validator software update" }, "hack")).toBe(false);
    expect(matchesTopic({ title: "Firm raises funding for a major Bitcoin purchase" }, "large_investment")).toBe(true);
    expect(matchesTopic({ title: "Institutional adoption report published" }, "large_investment")).toBe(false);
  });

  it("reports broad and topic-matched samples separately", () => {
    const events = [
      event("1", "Ethereum ETF filing advances", { "24h": 2 }),
      event("2", "Spot Ether exchange-traded fund approved", { "24h": -1 }),
      event("3", "Ethereum network upgrade ships", { "24h": 4 }),
    ];
    const result = runAnalytics(events, { ...baseIntent, topic: "etf" });
    expect(result).toMatchObject({
      kind: "scalar",
      value: 0.5,
      sampleSize: 2,
      topicFilter: { topic: "etf", broadSampleSize: 3, matchedSampleSize: 2 },
    });
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(["2", "1"]);
  });
});

describe("independent statistic edge cases", () => {
  it("handles odd, even, negative, positive, mixed, duplicate, and zero medians", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([-5, -1, -3])).toBe(-3);
    expect(median([1, 5, 3])).toBe(3);
    expect(median([-2, 0, 8, 4])).toBe(2);
    expect(median([2, 2, 2, 9])).toBe(2);
    expect(median([0, 0, 0])).toBe(0);
    expect(mean([])).toBeNull();
    expect(median([])).toBeNull();
  });

  it("excludes NULL and preserves per-horizon sample differences", () => {
    const result = runMultiHorizonAnalytics([
      event("1", "ETF filing one", { "1m": 1, "24h": 4 }),
      event("2", "ETF filing two", { "1m": null, "24h": 0 }),
      event("3", "ETF filing three", { "1m": -1, "24h": null }),
    ], { ...baseIntent, topic: "etf", horizon: null });
    expect(result.rows.find(({ horizon }) => horizon === "1m")).toMatchObject({ mean: 0, median: 0, sampleSize: 2 });
    expect(result.rows.find(({ horizon }) => horizon === "24h")).toMatchObject({ mean: 2, median: 2, sampleSize: 2 });
  });

  it("never formats rounded negative zero", () => {
    expect(formatPercent(-0.003)).toBe("0.00%");
    expect(formatPercent(-0.006)).toBe("-0.01%");
    expect(formatPercent(0.006)).toBe("+0.01%");
  });
});
