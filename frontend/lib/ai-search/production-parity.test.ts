import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { loadEnvConfig } from "@next/env";
import { createClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { ProductionAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { matchesTopic } from "@/lib/ai-search/topic-matcher";
import type { AiSearchIntent, AiTopic, AnalyticsResult } from "@/types/ai-search";
import { HORIZONS, type Asset, type Horizon, type SourceType } from "@/types/events";

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
  topic: null, actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
  amount: null, entity: null, assetRole: "any", sourceClass: null, sentiment: null, reactionSign: null, importance: null,
  horizon: "1m", metric: "mean",
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

function buildTopicParityIntents(): AiSearchIntent[] {
  const topic = (
    value: AiTopic,
    asset: Asset,
    overrides: Partial<AiSearchIntent> = {},
  ): AiSearchIntent => ({ ...baseIntent, asset, topic: value, ...overrides });
  return [
    topic("sec_filings", "ETH", { category: "regulation", dateFrom: "2024-01-01", dateTo: "2024-12-31", horizon: "24h", metric: "mean" }),
    topic("sec_filings", "BTC", { category: "regulation", intent: "rank", horizon: "24h", metric: "reaction", sort: "losers", limit: 10 }),
    topic("sec", "BTC", { horizon: null }),
    topic("sec", "ETH", { horizon: "4h", metric: "mean" }),
    topic("etf", "ETH", { horizon: null }),
    topic("etf", "BTC", { horizon: "24h", metric: "median" }),
    topic("hack", "SOL", { horizon: null }),
    topic("hack", "BTC", { intent: "rank", horizon: "1h", metric: "reaction", sort: "losers", limit: 10 }),
    topic("listing", "SOL", { horizon: "1h", metric: "mean" }),
    topic("listing", "BTC", { intent: "count", horizon: null, metric: "count" }),
    topic("lawsuit", "ETH", { horizon: "24h", metric: "median" }),
    topic("lawsuit", "BTC", { intent: "search", horizon: null, metric: "events" }),
    topic("macro", "BTC", { horizon: "4h", metric: "mean" }),
    topic("macro", "ETH", { horizon: "24h", metric: "sign_share" }),
    topic("fed", "BTC", { horizon: null }),
    topic("fed", "ETH", { horizon: "1h", metric: "median" }),
    topic("cpi", "BTC", { horizon: null }),
    topic("cpi", "ETH", { intent: "count", horizon: null, metric: "count" }),
    topic("upgrade", "ETH", { horizon: null }),
    topic("upgrade", "SOL", { intent: "rank", horizon: "4h", metric: "reaction", sort: "gainers", limit: 10 }),
    topic("staking", "ETH", { horizon: "24h", metric: "mean" }),
    topic("staking", "SOL", { intent: "search", horizon: null, metric: "events" }),
    topic("large_investment", "ETH", { horizon: null }),
    topic("large_investment", "BTC", { intent: "rank", horizon: "24h", metric: "reaction", sort: "gainers", limit: 10 }),
    topic("institutional_purchase", "BTC", { horizon: "24h", metric: "mean" }),
    topic("institutional_purchase", "ETH", { intent: "count", horizon: null, metric: "count" }),
    topic("funding", "SOL", { horizon: "4h", metric: "mean" }),
    topic("funding", "ETH", { intent: "search", horizon: null, metric: "events", sourceClass: "news_media" }),
    topic("acquisition", "BTC", { horizon: "24h", metric: "median" }),
    topic("acquisition", "ETH", { horizon: "24h", metric: "sign_share" }),
  ];
}

const REFERENCE_TOPIC_PATTERNS: Partial<Record<AiTopic, readonly RegExp[]>> = {
  sec: [/\bSEC\b/iu, /Securities\s+and\s+Exchange\s+Commission/iu],
  sec_filings: [/\bSEC\s+filings?\b/iu, /\bSecurities\s+and\s+Exchange\s+Commission\b[^.]{0,80}\bfilings?\b/iu, /\b(?:8-K|10-K|10-Q|S-1|19b-4)\b/iu, /registration\s+statement/iu],
  etf: [/\bETFs?\b/iu, /exchange[- ]traded\s+funds?/iu],
  hack: [/\bhack(?:ed|ing|s)?\b/iu, /\bexploit(?:ed|s|ing)?\b/iu, /security\s+breach/iu, /cyber(?:attack| attack)/iu],
  listing: [/\b(?:listing|listed|lists)\b/iu, /trading\s+debut/iu],
  lawsuit: [/\blawsuits?\b/iu, /\blitigation\b/iu, /\b(?:sues|sued)\b/iu],
  macro: [/\bmacroeconomic\b/iu, /\binflation\b/iu, /\binterest\s+rates?\b/iu, /\bcentral\s+banks?\b/iu, /\b(?:GDP|jobs report|payrolls?)\b/iu],
  fed: [/Federal\s+Reserve/iu, /\bFed\b/iu, /\bFOMC\b/iu],
  cpi: [/\bCPI\b/iu, /consumer\s+price\s+index/iu, /inflation\s+report/iu],
  upgrade: [/\bupgrades?\b/iu, /\bhard\s+fork\b/iu, /\bnetwork\s+update\b/iu],
  staking: [/\bstak(?:e|ed|es|ing)\b/iu, /proof[- ]of[- ]stake/iu],
  large_investment: [/\binvest(?:s|ed|ing)\b/iu, /\binvestments?\b(?!\s+(?:gains?|returns?|products?|funds?|vehicles?)\b)/iu, /\bfunding\b(?!\s+(?:gap|shortfall|cuts?|pressure|concerns?|crisis|issues?|problems?|needs?)\b)/iu, /\bfunded\b/iu, /\brais(?:e|es|ed|ing)\b[^.]{0,40}\b(?:million|billion|round|capital|funding)\b/iu, /\b(?:purchase|purchases|purchased|buys|bought)\b/iu, /\bacqui(?:res?|red|sition|sitions)\b/iu, /treasury\s+(?:buy|buys|purchase|purchases)/iu, /institutional\s+(?:buy|buys|purchase|purchases)/iu],
  institutional_purchase: [/\binstitutional\s+(?:buy|buys|buyer|purchase|purchases|purchased)\b/iu, /\btreasury\s+(?:buy|buys|purchase|purchases|purchased|reserve)\b/iu],
  funding: [/\bfund(?:ing|ed)\b/iu, /\bfundrais(?:e|es|ed|ing)\b/iu, /\brais(?:e|es|ed|ing)\b[^.]{0,40}\b(?:million|billion|round|capital)\b/iu, /\b(?:seed|Series\s+[A-Z])\s+round\b/iu],
  acquisition: [/\bacqui(?:res?|red|sition|sitions)\b/iu, /\btakeovers?\b/iu],
};

function referenceTopicMatch(row: Pick<ReferenceRow, "title">, topic: AiTopic): boolean {
  return (REFERENCE_TOPIC_PATTERNS[topic] ?? []).some((pattern) => pattern.test(row.title));
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

function referenceStandardDeviation(values: number[]): number | null {
  if (values.length < 2) return null;
  const average = values.reduce((sum, value) => sum + value, 0) / values.length;
  return round(Math.sqrt(values.reduce((sum, value) => sum + ((value - average) ** 2), 0) / (values.length - 1)));
}

function referenceStandardError(values: number[]): number | null {
  const deviation = referenceStandardDeviation(values);
  return deviation === null ? null : round(deviation / Math.sqrt(values.length));
}

function referenceTrimmedMean(values: number[]): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const trim = Math.floor(ordered.length * 0.05);
  return referenceMean(trim > 0 && trim * 2 < ordered.length ? ordered.slice(trim, -trim) : ordered);
}

function referenceWilson95(successes: number, sampleSize: number): { low: number; high: number } | null {
  if (!sampleSize) return null;
  const z = 1.959963984540054;
  const proportion = successes / sampleSize;
  const denominator = 1 + (z * z) / sampleSize;
  const center = (proportion + (z * z) / (2 * sampleSize)) / denominator;
  const margin = z * Math.sqrt((proportion * (1 - proportion) + (z * z) / (4 * sampleSize)) / sampleSize) / denominator;
  return { low: round(Math.max(0, (center - margin) * 100)), high: round(Math.min(100, (center + margin) * 100)) };
}

function referenceBroadFilter(rows: ReferenceRow[], intent: AiSearchIntent): ReferenceRow[] {
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
    if (intent.reactionSign && intent.asset && intent.horizon) {
      const value = row[reactionColumn(intent.asset, intent.horizon)];
      if (typeof value !== "number" || (intent.reactionSign === "positive" ? value <= 0 : value >= 0)) return false;
    }
    return true;
  });
}

function referenceFilter(rows: ReferenceRow[], intent: AiSearchIntent): ReferenceRow[] {
  const broad = referenceBroadFilter(rows, intent);
  return intent.topic ? broad.filter((row) => referenceTopicMatch(row, intent.topic!)) : broad;
}

function citationIds(result: AnalyticsResult): string[] {
  return result.citations.map(({ eventId }) => eventId);
}

function canonicalActual(result: AnalyticsResult): unknown {
  const topic = result.topicFilter ? { topicFilter: result.topicFilter } : {};
  if (result.kind === "search") return { kind: result.kind, matched: result.matched, returned: result.returned, citationIds: citationIds(result), ...topic };
  if (result.kind === "count") return { kind: result.kind, value: result.value, sampleSize: result.sampleSize, citationIds: citationIds(result), ...topic };
  if (result.kind === "scalar") return { kind: result.kind, metric: result.metric, value: result.value, sampleSize: result.sampleSize, standardDeviation: result.standardDeviation, standardError: result.standardError, trimmedMean5Percent: result.trimmedMean5Percent, citationIds: citationIds(result), ...topic };
  if (result.kind === "share") return { kind: result.kind, positivePercent: result.positivePercent, negativePercent: result.negativePercent, neutralPercent: result.neutralPercent, positive95Ci: result.positive95Ci, sampleSize: result.sampleSize, citationIds: citationIds(result), ...topic };
  if (result.kind === "ranking") return { kind: result.kind, direction: result.direction, sampleSize: result.sampleSize, items: result.items.map(({ eventId, reaction }) => ({ eventId, reaction })), citationIds: citationIds(result), ...topic };
  if (result.kind === "multi_horizon") return { kind: result.kind, rows: result.rows, citationIds: citationIds(result), ...topic };
  if (result.kind === "topic_ranking") return { kind: result.kind, metric: result.metric, items: result.items, citationIds: citationIds(result), ...topic };
  if (result.kind === "topic_comparison") return { kind: result.kind, metric: result.metric, left: result.left, right: result.right, difference: result.difference, citationIds: citationIds(result), ...topic };
  return { kind: result.kind, metric: result.metric, left: result.left, right: result.right, difference: result.difference, citationIds: citationIds(result), ...topic };
}

function referenceResult(rows: ReferenceRow[], intent: AiSearchIntent): unknown {
  const broad = referenceBroadFilter(rows, intent);
  const filtered = referenceFilter(rows, intent);
  const newest = [...filtered].sort((a, b) => b.published_at.localeCompare(a.published_at) || a.event_id.localeCompare(b.event_id));
  const topic = intent.topic ? { topicFilter: { topic: intent.topic, broadSampleSize: broad.length, matchedSampleSize: filtered.length } } : {};
  if (intent.intent === "search") {
    const selected = (intent.sort === "oldest" ? [...newest].reverse() : newest).slice(0, intent.limit);
    return { kind: "search", matched: filtered.length, returned: selected.length, citationIds: selected.map((row) => row.event_id), ...topic };
  }
  if (intent.intent === "count") {
    return { kind: "count", value: filtered.length, sampleSize: filtered.length, citationIds: newest.slice(0, intent.limit).map((row) => row.event_id), ...topic };
  }
  if (intent.intent === "aggregate" && intent.horizon === null) {
    const rowsByHorizon = HORIZONS.map((horizon) => {
      const column = reactionColumn(intent.asset!, horizon);
      const valued = newest.flatMap((row) => typeof row[column] === "number" ? [{ row, value: row[column] as number }] : []);
      const values = valued.map(({ value }) => value);
      return {
        horizon,
        mean: referenceMean(values),
        median: referenceMedian(values),
        positivePercent: values.length ? round(values.filter((value) => value > 0).length * 100 / values.length) : null,
        sampleSize: values.length,
        standardDeviation: referenceStandardDeviation(values),
        standardError: referenceStandardError(values),
        trimmedMean5Percent: referenceTrimmedMean(values),
        positive95Ci: referenceWilson95(values.filter((value) => value > 0).length, values.length),
        citations: valued.slice(0, intent.limit).map(({ row }) => row.event_id),
      };
    });
    const citationIds = [...new Set(rowsByHorizon.flatMap(({ citations }) => citations))].slice(0, 50);
    return {
      kind: "multi_horizon",
      rows: rowsByHorizon.map((row) => ({
        horizon: row.horizon,
        mean: row.mean,
        median: row.median,
        positivePercent: row.positivePercent,
        sampleSize: row.sampleSize,
        standardDeviation: row.standardDeviation,
        standardError: row.standardError,
        trimmedMean5Percent: row.trimmedMean5Percent,
        positive95Ci: row.positive95Ci,
      })),
      citationIds,
      ...topic,
    };
  }
  const column = reactionColumn(intent.asset!, intent.horizon!);
  const valued = newest.flatMap((row) => typeof row[column] === "number" ? [{ row, value: row[column] as number }] : []);
  if (intent.intent === "rank") {
    const direction = intent.sort as "gainers" | "losers";
    const items = [...valued].sort((a, b) => (direction === "gainers" ? b.value - a.value : a.value - b.value) || a.row.event_id.localeCompare(b.row.event_id)).slice(0, intent.limit);
    const mapped = items.map(({ row, value }) => ({ eventId: row.event_id, reaction: value }));
    return { kind: "ranking", direction, sampleSize: valued.length, items: mapped, citationIds: mapped.map(({ eventId }) => eventId), ...topic };
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
    return { kind: "comparison", metric: intent.metric, left, right, difference, citationIds: ids, ...topic };
  }
  const values = valued.map(({ value }) => value);
  const ids = valued.slice(0, intent.limit).map(({ row }) => row.event_id);
  if (intent.metric === "sign_share") {
    const percent = (count: number) => values.length ? round(count * 100 / values.length) : null;
    const positive = values.filter((value) => value > 0).length;
    return { kind: "share", positivePercent: percent(positive), negativePercent: percent(values.filter((value) => value < 0).length), neutralPercent: percent(values.filter((value) => value === 0).length), positive95Ci: referenceWilson95(positive, values.length), sampleSize: values.length, citationIds: ids, ...topic };
  }
  return { kind: "scalar", metric: intent.metric, value: intent.metric === "mean" ? referenceMean(values) : referenceMedian(values), sampleSize: values.length, standardDeviation: referenceStandardDeviation(values), standardError: referenceStandardError(values), trimmedMean5Percent: referenceTrimmedMean(values), citationIds: ids, ...topic };
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
    const neutralityIntent: AiSearchIntent = {
      ...baseIntent,
      asset: "ETH",
      category: "institutional_adoption",
      horizon: null,
      metric: "mean",
    };
    const neutralityActual = canonicalActual(await adapter.analyzeOverview(neutralityIntent));
    const neutralityExpected = referenceResult(rows, neutralityIntent);
    expect(numericParity(neutralityActual, neutralityExpected)).toBe(true);
    const institutionalAdoptionRows = referenceFilter(rows, neutralityIntent).length;
    expect(institutionalAdoptionRows).toBe(1_669);
    const topicIntents = buildTopicParityIntents();
    expect(topicIntents).toHaveLength(30);
    let topicContractMismatches = 0;
    let topicMappingMismatches = 0;
    const topicMappingMismatchDetails: Array<{ topic: AiTopic; asset: Asset; actual: number; expected: number }> = [];
    const topicResults: unknown[] = [];
    for (const intent of topicIntents) {
      const broad = referenceBroadFilter(rows, intent);
      const actualMatchedIds = broad.filter((row) => matchesTopic({ title: row.title }, intent.topic!)).map(({ event_id }) => event_id).sort();
      const expectedMatchedIds = broad.filter((row) => referenceTopicMatch(row, intent.topic!)).map(({ event_id }) => event_id).sort();
      if (!numericParity(actualMatchedIds, expectedMatchedIds)) {
        topicMappingMismatches += 1;
        topicMappingMismatchDetails.push({ topic: intent.topic!, asset: intent.asset!, actual: actualMatchedIds.length, expected: expectedMatchedIds.length });
      }
      const raw = intent.intent === "aggregate" && intent.horizon === null
        ? await adapter.analyzeOverview(intent)
        : await adapter.analyze(intent);
      const actual = canonicalActual(raw);
      if (
        raw.topicFilter?.topic !== intent.topic
        || raw.topicFilter.broadSampleSize > 10_000
        || raw.topicFilter.matchedSampleSize > raw.topicFilter.broadSampleSize
        || raw.citations.length > 50
      ) topicContractMismatches += 1;
      topicResults.push(actual);
    }
    if (topicMappingMismatchDetails.length) console.info("Topic mapping mismatch details", topicMappingMismatchDetails);
    expect(topicMappingMismatches).toBe(0);
    expect(topicContractMismatches).toBe(0);
    const resultSha256 = createHash("sha256").update(JSON.stringify(normalizedResults)).digest("hex");
    const topicResultSha256 = createHash("sha256").update(JSON.stringify(topicResults)).digest("hex");
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
      topicParityCases: topicIntents.length,
      topicContractMismatches,
      topicMappingMismatches,
      institutionalAdoptionRows,
      neutralityClassification: "NEUTRALITY_CAUSED_BY_DATA/FILTERING",
      neutralityResult: neutralityActual,
      tolerance: TOLERANCE,
      resultSha256,
      topicResultSha256,
    }, null, 2)}\n`);
    console.info("AI Search production parity", {
      events: rows.length,
      parityCases: intents.length,
      mismatches,
      topicParityCases: topicIntents.length,
      topicContractMismatches,
      topicMappingMismatches,
      institutionalAdoptionRows,
      neutralityClassification: "NEUTRALITY_CAUSED_BY_DATA/FILTERING",
      tolerance: TOLERANCE,
      resultSha256,
      topicResultSha256,
    });
  }, 300_000);
});
