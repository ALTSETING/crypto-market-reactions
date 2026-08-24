import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { loadEnvConfig } from "@next/env";
import { createClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { ProductionAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import type { AiSearchIntent, AnalyticsResult } from "@/types/ai-search";
import type { Asset, Horizon, SourceType } from "@/types/events";

loadEnvConfig(process.cwd());

const EXPECTED_PROJECT_REF = "ickflwksigaotygtdyko";
const EXPECTED_EVENTS = 9_073;
const TOLERANCE = 1e-9;
const REACTION_COLUMNS = [
  "btc_1m", "btc_5m", "btc_15m", "btc_1h", "btc_4h", "btc_24h",
  "eth_1m", "eth_5m", "eth_15m", "eth_1h", "eth_4h", "eth_24h",
  "sol_1m", "sol_5m", "sol_15m", "sol_1h", "sol_4h", "sol_24h",
] as const;
const SELECT = [
  "event_id", "slug", "title", "published_at", "related_assets", "category",
  "source_class_v2", "sentiment", "importance", ...REACTION_COLUMNS,
].join(",");

interface ReferenceRow {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  related_assets: Asset[];
  category: string;
  source_class_v2: SourceType;
  sentiment: string | null;
  importance: number | null;
  [key: string]: unknown;
}

const baseIntent: AiSearchIntent = {
  intent: "aggregate", asset: "BTC", dateFrom: null, dateTo: null, category: null,
  sourceClass: null, sentiment: null, importance: null, horizon: "1m", metric: "mean",
  sort: "newest", groupBy: "none", comparison: null, limit: 10,
};

function buildParityIntents(): AiSearchIntent[] {
  const assets: Asset[] = ["BTC", "ETH", "SOL"];
  const horizons: Horizon[] = ["1m", "5m", "15m", "1h", "4h", "24h"];
  const intents: AiSearchIntent[] = [];
  assets.forEach((asset, assetIndex) => horizons.forEach((horizon, horizonIndex) => {
    const metric = ["mean", "median", "sign_share"][(assetIndex * horizons.length + horizonIndex) % 3] as "mean" | "median" | "sign_share";
    intents.push({ ...baseIntent, asset, horizon, metric });
  }));
  intents.push(
    { ...baseIntent, intent: "rank", asset: "BTC", horizon: "24h", metric: "reaction", sort: "gainers", limit: 12 },
    { ...baseIntent, intent: "rank", asset: "ETH", horizon: "4h", metric: "reaction", sort: "losers", limit: 12 },
    { ...baseIntent, intent: "rank", asset: "SOL", horizon: "1h", metric: "reaction", sort: "losers", limit: 12 },
    { ...baseIntent, intent: "count", asset: "BTC", horizon: null, metric: "count", sourceClass: "news_media" },
    { ...baseIntent, intent: "count", asset: "ETH", horizon: null, metric: "count", sourceClass: "primary_document" },
    { ...baseIntent, intent: "count", asset: "SOL", horizon: null, metric: "count", sourceClass: "official_announcement" },
    { ...baseIntent, intent: "search", asset: "BTC", horizon: null, metric: "events", sourceClass: "news_media", limit: 8 },
    { ...baseIntent, intent: "search", asset: "ETH", horizon: null, metric: "events", sourceClass: "primary_document", limit: 8 },
    { ...baseIntent, intent: "search", asset: "SOL", horizon: null, metric: "events", sourceClass: "official_announcement", limit: 8 },
    ...assets.map((asset, index): AiSearchIntent => ({
      ...baseIntent,
      intent: "compare",
      asset,
      horizon: horizons[index * 2 + 1],
      metric: index % 2 === 0 ? "mean" : "median",
      groupBy: "source_class",
      comparison: { field: "sourceClass", left: "primary_document", right: "news_media" },
    })),
  );
  return intents;
}

function reactionColumn(asset: Asset, horizon: Horizon): string {
  return `${asset.toLowerCase()}_${horizon}`;
}

function round(value: number): number {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

function referenceMedian(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : round((sorted[middle - 1] + sorted[middle]) / 2);
}

function referenceMean(values: number[]): number | null {
  return values.length ? round(values.reduce((sum, value) => sum + value, 0) / values.length) : null;
}

function referenceFilter(rows: ReferenceRow[], intent: AiSearchIntent): ReferenceRow[] {
  return rows.filter((row) => {
    if (intent.asset && !row.related_assets.includes(intent.asset)) return false;
    if (intent.dateFrom && row.published_at.slice(0, 10) < intent.dateFrom) return false;
    if (intent.dateTo && row.published_at.slice(0, 10) > intent.dateTo) return false;
    if (intent.category && row.category !== intent.category) return false;
    if (intent.sourceClass && row.source_class_v2 !== intent.sourceClass) return false;
    const normalizedSentiment = row.sentiment === "bullish" || row.sentiment === "positive"
      ? "positive" : row.sentiment === "bearish" || row.sentiment === "negative" ? "negative" : row.sentiment;
    if (intent.sentiment && normalizedSentiment !== intent.sentiment) return false;
    if (intent.importance === "low" && !(row.importance !== null && row.importance < 0.33)) return false;
    if (intent.importance === "medium" && !(row.importance !== null && row.importance >= 0.33 && row.importance < 0.67)) return false;
    if (intent.importance === "high" && !(row.importance !== null && row.importance >= 0.67)) return false;
    return true;
  });
}

function citationIds(result: AnalyticsResult): string[] {
  return result.citations.map(({ eventId }) => eventId);
}

function canonicalActual(result: AnalyticsResult): unknown {
  if (result.kind === "search") return { kind: result.kind, matched: result.matched, returned: result.returned, citationIds: citationIds(result) };
  if (result.kind === "count") return { kind: result.kind, value: result.value, sampleSize: result.sampleSize, citationIds: citationIds(result) };
  if (result.kind === "scalar") return { kind: result.kind, metric: result.metric, value: result.value, sampleSize: result.sampleSize, citationIds: citationIds(result) };
  if (result.kind === "share") return { kind: result.kind, positivePercent: result.positivePercent, negativePercent: result.negativePercent, neutralPercent: result.neutralPercent, sampleSize: result.sampleSize, citationIds: citationIds(result) };
  if (result.kind === "ranking") return { kind: result.kind, direction: result.direction, sampleSize: result.sampleSize, items: result.items.map(({ eventId, reaction }) => ({ eventId, reaction })), citationIds: citationIds(result) };
  if (result.kind === "multi_horizon") return { kind: result.kind, metric: result.metric, rows: result.rows, median24h: result.median24h, positivePercent24h: result.positivePercent24h, citationIds: citationIds(result) };
  return { kind: result.kind, metric: result.metric, left: result.left, right: result.right, difference: result.difference, citationIds: citationIds(result) };
}

function referenceResult(rows: ReferenceRow[], intent: AiSearchIntent): unknown {
  const filtered = referenceFilter(rows, intent);
  const newest = [...filtered].sort((a, b) => b.published_at.localeCompare(a.published_at) || a.event_id.localeCompare(b.event_id));
  if (intent.intent === "search") {
    const selected = (intent.sort === "oldest" ? [...newest].reverse() : newest).slice(0, intent.limit);
    return { kind: "search", matched: filtered.length, returned: selected.length, citationIds: selected.map((row) => row.event_id) };
  }
  if (intent.intent === "count") {
    return { kind: "count", value: filtered.length, sampleSize: filtered.length, citationIds: newest.slice(0, intent.limit).map((row) => row.event_id) };
  }
  const column = reactionColumn(intent.asset!, intent.horizon!);
  const valued = newest.flatMap((row) => typeof row[column] === "number" ? [{ row, value: row[column] as number }] : []);
  if (intent.intent === "rank") {
    const direction = intent.sort as "gainers" | "losers";
    const items = [...valued].sort((a, b) => (direction === "gainers" ? b.value - a.value : a.value - b.value) || a.row.event_id.localeCompare(b.row.event_id)).slice(0, intent.limit);
    const mapped = items.map(({ row, value }) => ({ eventId: row.event_id, reaction: value }));
    return { kind: "ranking", direction, sampleSize: valued.length, items: mapped, citationIds: mapped.map(({ eventId }) => eventId) };
  }
  if (intent.intent === "compare" && intent.comparison) {
    const side = (sourceClass: SourceType) => {
      const values = valued.filter(({ row }) => row.source_class_v2 === sourceClass).map(({ value }) => value);
      return { sourceClass, value: intent.metric === "mean" ? referenceMean(values) : referenceMedian(values), sampleSize: values.length };
    };
    const left = side(intent.comparison.left);
    const right = side(intent.comparison.right);
    const difference = left.value === null || right.value === null ? null : round(left.value - right.value);
    const ids = valued.filter(({ row }) => row.source_class_v2 === left.sourceClass || row.source_class_v2 === right.sourceClass).slice(0, intent.limit).map(({ row }) => row.event_id);
    return { kind: "comparison", metric: intent.metric, left, right, difference, citationIds: ids };
  }
  const values = valued.map(({ value }) => value);
  const ids = valued.slice(0, intent.limit).map(({ row }) => row.event_id);
  if (intent.metric === "sign_share") {
    const percent = (count: number) => values.length ? round(count * 100 / values.length) : null;
    return { kind: "share", positivePercent: percent(values.filter((value) => value > 0).length), negativePercent: percent(values.filter((value) => value < 0).length), neutralPercent: percent(values.filter((value) => value === 0).length), sampleSize: values.length, citationIds: ids };
  }
  return { kind: "scalar", metric: intent.metric, value: intent.metric === "mean" ? referenceMean(values) : referenceMedian(values), sampleSize: values.length, citationIds: ids };
}

function numericParity(actual: unknown, expected: unknown): boolean {
  if (typeof actual === "number" && typeof expected === "number") return Math.abs(actual - expected) <= TOLERANCE;
  if (actual === null || expected === null || typeof actual !== "object" || typeof expected !== "object") return actual === expected;
  if (Array.isArray(actual) || Array.isArray(expected)) {
    return Array.isArray(actual) && Array.isArray(expected) && actual.length === expected.length && actual.every((value, index) => numericParity(value, expected[index]));
  }
  const actualRecord = actual as Record<string, unknown>;
  const expectedRecord = expected as Record<string, unknown>;
  return Object.keys(actualRecord).sort().join(",") === Object.keys(expectedRecord).sort().join(",")
    && Object.keys(actualRecord).every((key) => numericParity(actualRecord[key], expectedRecord[key]));
}

describe.skipIf(process.env.AI_PRODUCTION_PARITY !== "1")("production read-only AI Search parity", () => {
  it("matches an independent reference calculator for 30 production intents", async () => {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
    expect(url && key).toBeTruthy();
    expect(new URL(url!).hostname.split(".")[0]).toBe(EXPECTED_PROJECT_REF);
    const client = createClient(url!, key!, { auth: { persistSession: false, autoRefreshToken: false } });
    const rows: ReferenceRow[] = [];
    for (let from = 0; from < 10_000; from += 1_000) {
      const { data, error } = await client.from("events").select(SELECT).order("event_id").range(from, from + 999);
      if (error) throw new Error(error.message);
      rows.push(...((data ?? []) as unknown as ReferenceRow[]));
      if ((data ?? []).length < 1_000) break;
    }
    expect(rows).toHaveLength(EXPECTED_EVENTS);
    expect(new Set(rows.map(({ event_id }) => event_id)).size).toBe(EXPECTED_EVENTS);
    expect(new Set(rows.map(({ slug }) => slug)).size).toBe(EXPECTED_EVENTS);

    const adapter = new ProductionAiSearchDataAdapter(client, 20_000);
    const intents = buildParityIntents();
    expect(intents).toHaveLength(30);
    const normalizedResults: unknown[] = [];
    let mismatches = 0;
    for (const intent of intents) {
      const actual = canonicalActual(await adapter.analyze(intent));
      const expected = referenceResult(rows, intent);
      if (!numericParity(actual, expected)) mismatches += 1;
      normalizedResults.push(actual);
    }
    expect(mismatches).toBe(0);
    const resultSha256 = createHash("sha256").update(JSON.stringify(normalizedResults)).digest("hex");
    const reportDir = path.resolve(".tools");
    mkdirSync(reportDir, { recursive: true });
    writeFileSync(path.join(reportDir, "ai-search-production-parity.json"), `${JSON.stringify({
      projectRef: EXPECTED_PROJECT_REF,
      timestampUtc: new Date().toISOString(),
      events: rows.length,
      uniqueIds: new Set(rows.map(({ event_id }) => event_id)).size,
      uniqueSlugs: new Set(rows.map(({ slug }) => slug)).size,
      parityCases: intents.length,
      mismatches,
      tolerance: TOLERANCE,
      resultSha256,
    }, null, 2)}\n`);
    console.info("AI Search production parity", { events: rows.length, parityCases: intents.length, mismatches, tolerance: TOLERANCE, resultSha256 });
  }, 120_000);
});
