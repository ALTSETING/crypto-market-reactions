import { describe, expect, it } from "vitest";

import { runAnalytics } from "@/lib/ai-search/analytics";
import { AI_SEARCH_FIXTURES } from "@/lib/ai-search/fixtures";
import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent } from "@/types/ai-search";

const base: AiSearchIntent = {
  intent: "aggregate", asset: "ETH", dateFrom: "2024-01-01", dateTo: "2024-12-31",
  category: "regulation", sourceClass: "primary_document", sentiment: null, importance: null,
  horizon: "24h", metric: "mean", sort: "newest", groupBy: "none", comparison: null, limit: 50,
};

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
});
