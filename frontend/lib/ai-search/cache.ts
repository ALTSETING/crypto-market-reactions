import "server-only";

import type { AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import type { AiSearchIntent, AnalyticsResult, MultiHorizonAnalyticsResult } from "@/types/ai-search";

interface CacheEntry {
  expiresAt: number;
  result: AnalyticsResult;
}
export function normalizedIntentCacheKey(intent: AiSearchIntent): string {
  return JSON.stringify({
    intent: intent.intent,
    asset: intent.asset,
    dateFrom: intent.dateFrom,
    dateTo: intent.dateTo,
    category: intent.category,
    topic: intent.topic,
    sourceClass: intent.sourceClass,
    sentiment: intent.sentiment,
    reactionSign: intent.reactionSign,
    importance: intent.importance,
    horizon: intent.horizon,
    metric: intent.metric,
    sort: intent.sort,
    groupBy: intent.groupBy,
    comparison: intent.comparison,
    limit: intent.limit,
  });
}

export class CachedAiSearchDataAdapter implements AiSearchDataAdapter {
  private readonly entries = new Map<string, CacheEntry>();

  constructor(
    private readonly delegate: AiSearchDataAdapter,
    private readonly ttlMs = 30_000,
    private readonly maxEntries = 100,
  ) {}

  async analyze(intent: AiSearchIntent): Promise<AnalyticsResult> {
    const key = normalizedIntentCacheKey(intent);
    const now = Date.now();
    const hit = this.entries.get(key);
    if (hit && hit.expiresAt > now) return structuredClone(hit.result);
    if (hit) this.entries.delete(key);

    const result = await this.delegate.analyze(intent);
    if (this.entries.size >= this.maxEntries) {
      const oldest = this.entries.keys().next().value;
      if (oldest) this.entries.delete(oldest);
    }
    this.entries.set(key, { expiresAt: now + this.ttlMs, result: structuredClone(result) });
    return result;
  }

  async analyzeOverview(intent: AiSearchIntent): Promise<MultiHorizonAnalyticsResult> {
    const key = `overview:${normalizedIntentCacheKey(intent)}`;
    const now = Date.now();
    const hit = this.entries.get(key);
    if (hit?.expiresAt && hit.expiresAt > now && hit.result.kind === "multi_horizon") return structuredClone(hit.result);
    const result = await this.delegate.analyzeOverview(intent);
    this.entries.set(key, { expiresAt: now + this.ttlMs, result: structuredClone(result) });
    return result;
  }
}
