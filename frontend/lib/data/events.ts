import "server-only";

import { getSupabaseServerClient } from "@/lib/supabase/server";
import { reactionColumn } from "@/lib/reactions";
import { isValidEventSlug, nextUtcDate } from "@/lib/validation/events-query";
import type {
  EventDetail,
  EventListItem,
  EventsPage,
  EventsQuery,
  SitemapEvent,
} from "@/types/events";

const SITEMAP_BATCH_SIZE = 1_000;
const SITEMAP_URL_LIMIT = 50_000;

export const EVENT_LIST_SELECT = [
  "event_id",
  "slug",
  "title",
  "published_at",
  "source",
  "primary_asset",
  "related_assets",
  "category",
  "sentiment",
  "importance",
  "btc_1m",
  "btc_5m",
  "btc_15m",
  "btc_1h",
  "btc_4h",
  "btc_24h",
  "btc_average_reaction",
  "eth_1m",
  "eth_5m",
  "eth_15m",
  "eth_1h",
  "eth_4h",
  "eth_24h",
  "eth_average_reaction",
  "sol_1m",
  "sol_5m",
  "sol_15m",
  "sol_1h",
  "sol_4h",
  "sol_24h",
  "sol_average_reaction",
].join(",");

export const EVENT_DETAIL_SELECT = [
  EVENT_LIST_SELECT,
  "source_url",
  "sentiment_score",
  "reaction_methodology",
  "reaction_value_unit",
  "btc_reaction_source",
  "btc_reference_time",
  "btc_reference_latency_minutes",
  "eth_reaction_source",
  "eth_reference_time",
  "eth_reference_latency_minutes",
  "sol_reaction_source",
  "sol_reference_time",
  "sol_reference_latency_minutes",
].join(",");

export class EventsDataError extends Error {
  readonly code = "EVENTS_DATA_UNAVAILABLE";

  constructor(message = "Events data is temporarily unavailable.") {
    super(message);
    this.name = "EventsDataError";
  }
}

export async function getEvents(params: EventsQuery): Promise<EventsPage> {
  const supabase = getSupabaseServerClient();
  let request = supabase
    .from("events")
    .select(EVENT_LIST_SELECT, { count: "exact" });

  if (params.query) {
    request = request.textSearch("search_vector", params.query, {
      config: "english",
      type: "websearch",
    });
  }
  if (params.asset) request = request.contains("related_assets", [params.asset]);
  if (params.source) request = request.eq("source", params.source);
  if (params.from) request = request.gte("published_at", `${params.from}T00:00:00.000Z`);
  if (params.to) request = request.lt("published_at", nextUtcDate(params.to));
  const selectedReactionColumn = params.asset
    ? String(reactionColumn(params.asset, params.horizon))
    : null;
  if (params.marketDataOnly && selectedReactionColumn) {
    request = request.not(selectedReactionColumn, "is", null);
  }

  const fromRow = (params.page - 1) * params.pageSize;
  const toRow = fromRow + params.pageSize - 1;
  if ((params.sort === "growth" || params.sort === "decline") && selectedReactionColumn) {
    request = request.order(selectedReactionColumn, {
      ascending: params.sort === "decline",
      nullsFirst: false,
    });
  }
  request = request.order("published_at", { ascending: params.sort === "oldest" });
  request = request.order("event_id", { ascending: params.sort === "oldest" });
  const { data, error, count } = await request.range(fromRow, toRow);

  if (error) {
    console.error("Supabase events query failed", {
      code: error.code,
      message: error.message,
    });
    throw new EventsDataError();
  }

  const total = count ?? 0;
  return {
    items: (data ?? []) as unknown as EventListItem[],
    page: params.page,
    pageSize: params.pageSize,
    total,
    totalPages: total === 0 ? 0 : Math.ceil(total / params.pageSize),
  };
}

export async function getEventBySlug(slug: string): Promise<EventDetail | null> {
  if (!isValidEventSlug(slug)) return null;

  const { data, error } = await getSupabaseServerClient()
    .from("events")
    .select(EVENT_DETAIL_SELECT)
    .eq("slug", slug)
    .maybeSingle();

  if (error) {
    console.error("Supabase event lookup failed", {
      code: error.code,
      message: error.message,
    });
    throw new EventsDataError();
  }
  return data as unknown as EventDetail | null;
}

export async function getSitemapEvents(): Promise<SitemapEvent[]> {
  const supabase = getSupabaseServerClient();
  const events: SitemapEvent[] = [];

  for (let from = 0; from < SITEMAP_URL_LIMIT; from += SITEMAP_BATCH_SIZE) {
    const { data, error } = await supabase
      .from("events")
      .select("slug,updated_at")
      .order("event_id", { ascending: true })
      .range(from, from + SITEMAP_BATCH_SIZE - 1);

    if (error) {
      console.error("Supabase sitemap query failed", {
        code: error.code,
        message: error.message,
        from,
      });
      throw new EventsDataError("The event sitemap is temporarily unavailable.");
    }

    const batch = (data ?? []) as unknown as SitemapEvent[];
    events.push(...batch);
    if (batch.length < SITEMAP_BATCH_SIZE) break;
  }

  if (events.length >= SITEMAP_URL_LIMIT) {
    throw new EventsDataError("The event sitemap has reached its single-file URL limit.");
  }

  const uniqueSlugs = new Set<string>();
  for (const event of events) {
    if (!isValidEventSlug(event.slug) || uniqueSlugs.has(event.slug)) {
      throw new EventsDataError("The event sitemap contains an invalid or duplicate slug.");
    }
    uniqueSlugs.add(event.slug);
  }
  return events;
}
