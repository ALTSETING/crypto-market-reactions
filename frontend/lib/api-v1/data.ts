import "server-only";

import type { SupabaseClient } from "@supabase/supabase-js";

import { CachedAiSearchDataAdapter } from "@/lib/ai-search/cache";
import { ProductionAiSearchDataAdapter, AiSearchDataError, type AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { classifySemanticEvent } from "@/lib/ai-search/semantic-matcher";
import type { AiSearchIntent, AiTopic } from "@/types/ai-search";
import { ASSETS, HORIZONS, type Asset, type EventCategory, type SourceType } from "@/types/events";
import { ApiV1Error } from "@/lib/api-v1/errors";
import {
  API_MAX_TOPIC_SCAN_ROWS,
  type ApiCursor,
  type EventsApiQuery,
  type PublicEvent,
  type PublicReactionValues,
  type ReactionApiRow,
  type ReactionsApiQuery,
} from "@/lib/api-v1/types";
import { getSupabaseServerClient } from "@/lib/supabase/server";

const TOPIC_SCAN_PAGE_SIZE = 1_000;
const CACHE_TTL_MS = 30_000;
const CACHE_MAX_ENTRIES = 200;

const API_EVENT_SELECT = [
  "event_id", "slug", "title", "published_at", "source", "source_url", "primary_asset", "related_assets",
  "category", "source_class_v2",
  ...ASSETS.flatMap((asset) => HORIZONS.map((horizon) => `${asset.toLowerCase()}_${horizon}`)),
].join(",");

interface ApiEventRow {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  source: string;
  source_url: string;
  primary_asset: Asset | null;
  related_assets: Asset[];
  category: EventCategory;
  source_class_v2: SourceType;
  [key: string]: unknown;
}

interface ApiEventQueryResult {
  data: unknown[] | null;
  error: { message: string } | null;
}

interface ApiEventQuery extends PromiseLike<ApiEventQueryResult> {
  textSearch(column: string, query: string, options: { config: string; type: "websearch" }): ApiEventQuery;
  contains(column: string, value: unknown): ApiEventQuery;
  eq(column: string, value: unknown): ApiEventQuery;
  gte(column: string, value: unknown): ApiEventQuery;
  lte(column: string, value: unknown): ApiEventQuery;
  or(filters: string): ApiEventQuery;
  order(column: string, options: { ascending: boolean }): ApiEventQuery;
  limit(count: number): ApiEventQuery;
  range(from: number, to: number): ApiEventQuery;
}

export interface EventsDataParams extends Omit<EventsApiQuery, "cursor"> {
  cursor: ApiCursor | null;
}

export interface EventsDataResult {
  items: PublicEvent[];
  hasMore: boolean;
}

interface CacheEntry<T> {
  expiresAt: number;
  value: T;
}

function isPublicSourceUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    const hostname = url.hostname.toLowerCase();
    return hostname !== "localhost"
      && hostname !== "127.0.0.1"
      && hostname !== "::1"
      && !hostname.endsWith(".local")
      && !/^10\./u.test(hostname)
      && !/^192\.168\./u.test(hostname)
      && !/^172\.(?:1[6-9]|2\d|3[01])\./u.test(hostname);
  } catch {
    return false;
  }
}

function reactionValues(row: ApiEventRow): PublicReactionValues {
  return Object.fromEntries(ASSETS.map((asset) => [
    asset,
    Object.fromEntries(HORIZONS.map((horizon) => {
      const value = row[`${asset.toLowerCase()}_${horizon}`];
      if (value !== null && typeof value !== "number") throw new Error("Invalid Reaction V2 value");
      return [horizon, value as number | null];
    })),
  ])) as PublicReactionValues;
}

function publicEvent(row: ApiEventRow, topic: AiTopic | null): PublicEvent {
  return {
    id: row.event_id,
    slug: row.slug,
    title: row.title,
    publishedAt: row.published_at,
    source: row.source,
    ...(isPublicSourceUrl(row.source_url) ? { sourceUrl: row.source_url } : {}),
    primaryAsset: row.primary_asset,
    relatedAssets: row.related_assets,
    category: row.category,
    sourceClass: row.source_class_v2,
    ...(topic ? { topic } : {}),
    reactionV2: reactionValues(row),
  };
}

function baseTopicIntent(asset: Asset, topic: AiTopic): AiSearchIntent {
  const anyRole = topic === "funding" || topic === "acquisition";
  return {
    intent: "search",
    asset,
    dateFrom: null,
    dateTo: null,
    category: null,
    topic,
    actorType: "unknown",
    action: null,
    direction: "unknown",
    magnitude: "unknown",
    amount: null,
    entity: null,
    assetRole: anyRole ? "any" : "primary",
    sourceClass: null,
    sentiment: null,
    reactionSign: null,
    importance: null,
    horizon: null,
    metric: "events",
    sort: "newest",
    groupBy: "none",
    comparison: null,
    limit: 50,
  };
}

function topicMatches(row: ApiEventRow, requestedAsset: Asset | null, topic: AiTopic): boolean {
  const assets = requestedAsset ? [requestedAsset] : row.related_assets;
  return assets.some((asset) => classifySemanticEvent({
    title: row.title,
    assets: row.related_assets,
    primaryAsset: row.primary_asset,
    category: row.category,
  }, baseTopicIntent(asset, topic)).matched);
}

function applyFilters(
  request: ApiEventQuery,
  params: EventsDataParams,
) {
  let query = request;
  if (params.search) query = query.textSearch("search_vector", params.search, { config: "english", type: "websearch" });
  if (params.asset) query = query.contains("related_assets", [params.asset]);
  if (params.category) query = query.eq("category", params.category);
  if (params.sourceClass) query = query.eq("source_class_v2", params.sourceClass);
  if (params.dateFrom) query = query.gte("published_at", `${params.dateFrom}T00:00:00.000Z`);
  if (params.dateTo) query = query.lte("published_at", `${params.dateTo}T23:59:59.999Z`);
  if (params.cursor) {
    query = query.or(`published_at.lt.${params.cursor.publishedAt},and(published_at.eq.${params.cursor.publishedAt},event_id.gt.${params.cursor.id})`);
  }
  return query.order("published_at", { ascending: false }).order("event_id", { ascending: true });
}

export class ApiV1DataService {
  private readonly cache = new Map<string, CacheEntry<EventsDataResult | PublicEvent | null>>();

  constructor(private readonly client: SupabaseClient = getSupabaseServerClient()) {}

  async listEvents(params: EventsDataParams): Promise<EventsDataResult> {
    const cacheKey = `events:${JSON.stringify(params)}`;
    const cached = this.readCache<EventsDataResult>(cacheKey);
    if (cached) return structuredClone(cached);
    try {
      const rows = params.topic
        ? await this.topicRows(params)
        : await this.directRows(params);
      const hasMore = rows.length > params.limit;
      const result = {
        items: rows.slice(0, params.limit).map((row) => publicEvent(row, params.topic)),
        hasMore,
      };
      this.writeCache(cacheKey, result);
      return result;
    } catch (error) {
      if (error instanceof ApiV1Error) throw error;
      console.error("API V1 events query failed", { name: error instanceof Error ? error.name : "UnknownError" });
      throw new ApiV1Error(503, "SERVICE_UNAVAILABLE", "Historical events are temporarily unavailable.");
    }
  }

  async getEventBySlug(slug: string): Promise<PublicEvent | null> {
    const cacheKey = `event:${slug}`;
    const cached = this.readCache<PublicEvent | null>(cacheKey);
    if (cached !== undefined) return cached ? structuredClone(cached) : null;
    try {
      const { data, error } = await this.client
        .from("events")
        .select(API_EVENT_SELECT)
        .eq("slug", slug)
        .maybeSingle();
      if (error) throw error;
      const result = data ? publicEvent(data as unknown as ApiEventRow, null) : null;
      this.writeCache(cacheKey, result);
      return result;
    } catch (error) {
      console.error("API V1 event lookup failed", { name: error instanceof Error ? error.name : "UnknownError" });
      throw new ApiV1Error(503, "SERVICE_UNAVAILABLE", "Historical events are temporarily unavailable.");
    }
  }

  private async directRows(params: EventsDataParams): Promise<ApiEventRow[]> {
    const query = applyFilters(
      this.client.from("events").select(API_EVENT_SELECT) as unknown as ApiEventQuery,
      params,
    ).limit(params.limit + 1);
    const { data, error } = await query;
    if (error) throw error;
    return (data ?? []) as unknown as ApiEventRow[];
  }

  private async topicRows(params: EventsDataParams): Promise<ApiEventRow[]> {
    const matches: ApiEventRow[] = [];
    let scanned = 0;
    while (scanned < API_MAX_TOPIC_SCAN_ROWS && matches.length <= params.limit) {
      const batchSize = Math.min(TOPIC_SCAN_PAGE_SIZE, API_MAX_TOPIC_SCAN_ROWS - scanned);
      const query = applyFilters(
        this.client.from("events").select(API_EVENT_SELECT) as unknown as ApiEventQuery,
        params,
      )
        .range(scanned, scanned + batchSize - 1);
      const { data, error } = await query;
      if (error) throw error;
      const rows = (data ?? []) as unknown as ApiEventRow[];
      matches.push(...rows.filter((row) => topicMatches(row, params.asset, params.topic!)));
      scanned += rows.length;
      if (rows.length < batchSize) return matches;
    }
    if (matches.length <= params.limit && scanned >= API_MAX_TOPIC_SCAN_ROWS) {
      throw new ApiV1Error(400, "INVALID_PARAMETER", "The topic query is too broad; add an asset or date range.");
    }
    return matches;
  }

  private readCache<T>(key: string): T | undefined {
    const entry = this.cache.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt <= Date.now()) {
      this.cache.delete(key);
      return undefined;
    }
    return entry.value as T;
  }

  private writeCache<T extends EventsDataResult | PublicEvent | null>(key: string, value: T): void {
    if (this.cache.size >= CACHE_MAX_ENTRIES) {
      const oldest = this.cache.keys().next().value;
      if (oldest) this.cache.delete(oldest);
    }
    this.cache.set(key, { expiresAt: Date.now() + CACHE_TTL_MS, value });
  }
}

export class ApiV1ReactionService {
  constructor(private readonly adapter: AiSearchDataAdapter) {}

  async query(params: ReactionsApiQuery): Promise<ReactionApiRow[]> {
    const intent: AiSearchIntent = {
      intent: "aggregate",
      asset: params.asset,
      dateFrom: params.dateFrom,
      dateTo: params.dateTo,
      category: null,
      topic: params.topic,
      actorType: "unknown",
      action: null,
      direction: "unknown",
      magnitude: "unknown",
      amount: null,
      entity: null,
      assetRole: params.topic === "funding" || params.topic === "acquisition" ? "any" : "primary",
      sourceClass: null,
      sentiment: null,
      reactionSign: params.direction,
      importance: null,
      horizon: null,
      metric: "mean",
      sort: "newest",
      groupBy: "none",
      comparison: null,
      limit: 50,
    };
    try {
      const result = await this.adapter.analyzeOverview(intent);
      return result.rows
        .filter((row) => params.horizon === null || row.horizon === params.horizon)
        .map((row) => ({
          horizon: row.horizon,
          matchedArticles: row.topicFilter?.matchedSampleSize ?? row.sampleSize,
          independentEvents: row.sampleSize,
          mean: row.mean,
          median: row.median,
          positivePercent: row.positivePercent,
          negativePercent: row.negativePercent,
          sampleSize: row.sampleSize,
        }));
    } catch (error) {
      if (error instanceof AiSearchDataError) {
        throw new ApiV1Error(503, "SERVICE_UNAVAILABLE", "Historical analytics are temporarily unavailable.");
      }
      throw error;
    }
  }
}

let dataService: ApiV1DataService | undefined;
let reactionService: ApiV1ReactionService | undefined;

export function getApiV1DataService(): ApiV1DataService {
  dataService ??= new ApiV1DataService();
  return dataService;
}

export function getApiV1ReactionService(): ApiV1ReactionService {
  reactionService ??= new ApiV1ReactionService(
    new CachedAiSearchDataAdapter(new ProductionAiSearchDataAdapter(), 60_000, 200),
  );
  return reactionService;
}
