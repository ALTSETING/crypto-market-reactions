import { describe, expect, it, vi } from "vitest";

import { CachedAiSearchDataAdapter, normalizedIntentCacheKey } from "@/lib/ai-search/cache";
import type { AiSearchIntent, AnalyticsResult } from "@/types/ai-search";

const intent: AiSearchIntent = {
  intent: "count", asset: "BTC", dateFrom: null, dateTo: null, category: null,
  topic: null, sourceClass: null, sentiment: null, reactionSign: null, importance: null,
  horizon: null, metric: "count",
  sort: "newest", groupBy: "none", comparison: null, limit: 10,
};
const result: AnalyticsResult = { kind: "count", value: 2, sampleSize: 2, citations: [] };

describe("AI Search result cache", () => {
  it("uses a stable normalized key and caches only completed analytics results", async () => {
    const analyze = vi.fn().mockResolvedValue(result);
    const cache = new CachedAiSearchDataAdapter({ analyze, analyzeOverview: vi.fn() }, 30_000, 10);
    expect(normalizedIntentCacheKey(intent)).toBe(normalizedIntentCacheKey({ ...intent }));
    await expect(cache.analyze(intent)).resolves.toEqual(result);
    await expect(cache.analyze({ ...intent })).resolves.toEqual(result);
    expect(analyze).toHaveBeenCalledTimes(1);
  });

  it("does not cache provider/adapter errors", async () => {
    const analyze = vi.fn().mockRejectedValueOnce(new Error("temporary")).mockResolvedValue(result);
    const cache = new CachedAiSearchDataAdapter({ analyze, analyzeOverview: vi.fn() });
    await expect(cache.analyze(intent)).rejects.toThrow("temporary");
    await expect(cache.analyze(intent)).resolves.toEqual(result);
    expect(analyze).toHaveBeenCalledTimes(2);
  });
});
