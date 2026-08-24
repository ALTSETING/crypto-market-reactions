import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

import { runAnalytics } from "@/lib/ai-search/analytics";
import { CachedAiSearchDataAdapter } from "@/lib/ai-search/cache";
import { AI_SEARCH_FIXTURES } from "@/lib/ai-search/fixtures";
import { getSupabaseServerClient } from "@/lib/supabase/server";
import type { AiSearchIntent, AnalyticsEvent, AnalyticsResult } from "@/types/ai-search";
import { ASSETS, EVENT_CATEGORIES, HORIZONS, SOURCE_TYPES, type Asset, type EventCategory, type Horizon, type SourceType } from "@/types/events";

const MAX_SCAN_ROWS = 10_000;
const PAGE_SIZE = 1_000;
const DEFAULT_TIMEOUT_MS = 8_000;

const REACTION_COLUMN: Record<Asset, Record<Horizon, string>> = Object.fromEntries(
  ASSETS.map((asset) => [
    asset,
    Object.fromEntries(HORIZONS.map((horizon) => [horizon, `${asset.toLowerCase()}_${horizon}`])),
  ]),
) as Record<Asset, Record<Horizon, string>>;

const PUBLIC_BASE_COLUMNS = [
  "event_id", "slug", "title", "published_at", "related_assets", "category",
  "source_class_v2", "sentiment", "importance",
] as const;

interface QueryBuilder {
  contains(column: string, value: unknown): QueryBuilder;
  gte(column: string, value: unknown): QueryBuilder;
  lte(column: string, value: unknown): QueryBuilder;
  lt(column: string, value: unknown): QueryBuilder;
  eq(column: string, value: unknown): QueryBuilder;
  in(column: string, values: readonly unknown[]): QueryBuilder;
  not(column: string, operator: string, value: unknown): QueryBuilder;
  order(column: string, options: { ascending: boolean; nullsFirst?: boolean }): QueryBuilder;
  limit(count: number): QueryBuilder;
  range(from: number, to: number): QueryBuilder;
  abortSignal(signal: AbortSignal): QueryBuilder;
}

interface QueryResult {
  data: unknown[] | null;
  error: { message: string } | null;
  count: number | null;
}

async function executeQuery(builder: QueryBuilder): Promise<QueryResult> {
  return await (builder as unknown as Promise<QueryResult>);
}

interface ProductionRow {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  related_assets: unknown;
  category: unknown;
  source_class_v2: unknown;
  sentiment: unknown;
  importance: unknown;
  [key: string]: unknown;
}

export class AiSearchDataError extends Error {
  constructor(
    readonly code: "AI_DATA_UNAVAILABLE" | "QUERY_TOO_BROAD",
    message: string,
  ) {
    super(message);
    this.name = "AiSearchDataError";
  }
}

export interface AiSearchDataAdapter {
  analyze(intent: AiSearchIntent): Promise<AnalyticsResult>;
}

export class FixtureAiSearchDataAdapter implements AiSearchDataAdapter {
  async analyze(intent: AiSearchIntent): Promise<AnalyticsResult> {
    return runAnalytics(AI_SEARCH_FIXTURES, intent);
  }
}

export class ProductionAiSearchDataAdapter implements AiSearchDataAdapter {
  constructor(
    private readonly client: SupabaseClient = getSupabaseServerClient(),
    private readonly timeoutMs = DEFAULT_TIMEOUT_MS,
  ) {}

  async analyze(intent: AiSearchIntent): Promise<AnalyticsResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      if (intent.intent === "search" || intent.intent === "count") {
        return await this.runCountOrSearch(intent, controller.signal);
      }
      if (intent.intent === "rank") return await this.runRanking(intent, controller.signal);
      return await this.runAggregate(intent, controller.signal);
    } catch (error) {
      if (error instanceof AiSearchDataError) throw error;
      console.error("AI Search production adapter failed", {
        name: error instanceof Error ? error.name : "UnknownError",
      });
      throw new AiSearchDataError("AI_DATA_UNAVAILABLE", "Historical analytics are temporarily unavailable.");
    } finally {
      clearTimeout(timeout);
    }
  }

  private selectColumns(intent: AiSearchIntent): string {
    const reaction = intent.asset && intent.horizon ? REACTION_COLUMN[intent.asset][intent.horizon] : null;
    return [...PUBLIC_BASE_COLUMNS, ...(reaction ? [reaction] : [])].join(",");
  }

  private applyFilters(builder: QueryBuilder, intent: AiSearchIntent): QueryBuilder {
    let query = builder;
    if (intent.asset) query = query.contains("related_assets", [intent.asset]);
    if (intent.dateFrom) query = query.gte("published_at", `${intent.dateFrom}T00:00:00.000Z`);
    if (intent.dateTo) query = query.lte("published_at", `${intent.dateTo}T23:59:59.999Z`);
    if (intent.category) query = query.eq("category", intent.category);
    if (intent.sourceClass) query = query.eq("source_class_v2", intent.sourceClass);
    if (intent.sentiment === "positive") query = query.in("sentiment", ["positive", "bullish"]);
    if (intent.sentiment === "negative") query = query.in("sentiment", ["negative", "bearish"]);
    if (intent.sentiment === "neutral") query = query.eq("sentiment", "neutral");
    if (intent.importance === "low") query = query.lt("importance", 0.33);
    if (intent.importance === "medium") query = query.gte("importance", 0.33).lt("importance", 0.67);
    if (intent.importance === "high") query = query.gte("importance", 0.67);
    return query;
  }

  private baseQuery(intent: AiSearchIntent, count: "exact" | undefined = undefined): QueryBuilder {
    const builder = this.client
      .from("events")
      .select(this.selectColumns(intent), count ? { count } : undefined) as unknown as QueryBuilder;
    return this.applyFilters(builder, intent);
  }

  private async runCountOrSearch(intent: AiSearchIntent, signal: AbortSignal): Promise<AnalyticsResult> {
    const query = this.baseQuery(intent, "exact")
      .order("published_at", { ascending: intent.sort === "oldest" })
      .order("event_id", { ascending: intent.sort !== "oldest" })
      .limit(intent.limit)
      .abortSignal(signal);
    const { data, error, count } = await executeQuery(query);
    if (error) throw new Error(error.message);
    const events = this.rowsToEvents((data ?? []) as unknown as ProductionRow[], intent);
    const localIntent = { ...intent, intent: intent.intent, limit: intent.limit };
    const local = runAnalytics(events, localIntent);
    const matched = count ?? 0;
    if (local.kind === "search") return { ...local, matched };
    if (local.kind === "count") return { ...local, value: matched, sampleSize: matched };
    throw new Error("Unexpected bounded analytics result");
  }

  private async runRanking(intent: AiSearchIntent, signal: AbortSignal): Promise<AnalyticsResult> {
    if (!intent.asset || !intent.horizon) throw new Error("Validated ranking is missing asset or horizon");
    const reactionColumn = REACTION_COLUMN[intent.asset][intent.horizon];
    const query = this.baseQuery(intent, "exact")
      .not(reactionColumn, "is", null)
      .order(reactionColumn, { ascending: intent.sort === "losers", nullsFirst: false })
      .order("event_id", { ascending: true })
      .limit(intent.limit)
      .abortSignal(signal);
    const { data, error, count } = await executeQuery(query);
    if (error) throw new Error(error.message);
    const result = runAnalytics(this.rowsToEvents((data ?? []) as unknown as ProductionRow[], intent), intent);
    if (result.kind !== "ranking") throw new Error("Unexpected ranking result");
    return { ...result, sampleSize: count ?? 0 };
  }

  private async runAggregate(intent: AiSearchIntent, signal: AbortSignal): Promise<AnalyticsResult> {
    if (!intent.asset || !intent.horizon) throw new Error("Validated aggregate is missing asset or horizon");
    const reactionColumn = REACTION_COLUMN[intent.asset][intent.horizon];
    const countQuery = this.baseQuery(intent, "exact").not(reactionColumn, "is", null).limit(1).abortSignal(signal);
    const { error: countError, count } = await executeQuery(countQuery);
    if (countError) throw new Error(countError.message);
    if ((count ?? 0) > MAX_SCAN_ROWS) {
      throw new AiSearchDataError("QUERY_TOO_BROAD", "Too many events match. Add an asset, date, category, or source filter.");
    }

    const rows: ProductionRow[] = [];
    for (let from = 0; from < (count ?? 0); from += PAGE_SIZE) {
      const page = this.baseQuery(intent)
        .not(reactionColumn, "is", null)
        .order("event_id", { ascending: true })
        .range(from, Math.min(from + PAGE_SIZE - 1, (count ?? 0) - 1))
        .abortSignal(signal);
      const { data, error } = await executeQuery(page);
      if (error) throw new Error(error.message);
      rows.push(...((data ?? []) as unknown as ProductionRow[]));
    }
    return runAnalytics(this.rowsToEvents(rows, intent), intent);
  }

  private rowsToEvents(rows: ProductionRow[], intent: AiSearchIntent): AnalyticsEvent[] {
    return rows.map((row) => {
      if (!Array.isArray(row.related_assets) || !row.related_assets.every((asset) => ASSETS.includes(asset as Asset))) {
        throw new Error("Invalid related_assets in public analytics row");
      }
      if (!EVENT_CATEGORIES.includes(row.category as EventCategory)) throw new Error("Invalid category in public analytics row");
      if (!SOURCE_TYPES.includes(row.source_class_v2 as SourceType)) throw new Error("Invalid source class in public analytics row");
      const reactionV2 = Object.fromEntries(ASSETS.map((asset) => [
        asset,
        Object.fromEntries(HORIZONS.map((horizon) => [horizon, null])),
      ])) as AnalyticsEvent["reactionV2"];
      if (intent.asset && intent.horizon) {
        const raw = row[REACTION_COLUMN[intent.asset][intent.horizon]];
        if (raw !== null && typeof raw !== "number") throw new Error("Invalid Reaction V2 value");
        reactionV2[intent.asset][intent.horizon] = raw as number | null;
      }
      const sentiment = row.sentiment === "positive" || row.sentiment === "bullish"
        ? "positive"
        : row.sentiment === "negative" || row.sentiment === "bearish"
          ? "negative"
          : row.sentiment === "neutral" ? "neutral" : null;
      const importance = typeof row.importance !== "number"
        ? null
        : row.importance < 0.33 ? "low" : row.importance < 0.67 ? "medium" : "high";
      return {
        eventId: row.event_id,
        slug: row.slug,
        title: row.title,
        publishedAt: row.published_at,
        assets: row.related_assets as Asset[],
        category: row.category as EventCategory,
        sourceClass: row.source_class_v2 as SourceType,
        sentiment,
        importance,
        reactionV2,
      };
    });
  }
}

let cachedProductionAdapter: AiSearchDataAdapter | undefined;

export function getAiSearchDataAdapter(): AiSearchDataAdapter {
  const configured = process.env.AI_SEARCH_DATA_ADAPTER?.trim().toLowerCase();
  if (configured === "production") {
    cachedProductionAdapter ??= new CachedAiSearchDataAdapter(new ProductionAiSearchDataAdapter());
    return cachedProductionAdapter;
  }
  if (configured === "fixture" && process.env.NODE_ENV !== "production") return new FixtureAiSearchDataAdapter();
  throw new Error("AI Search data adapter is not configured for this environment.");
}
