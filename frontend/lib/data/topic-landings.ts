import "server-only";

import { runMultiHorizonAnalytics } from "@/lib/ai-search/analytics";
import { matchesTopic } from "@/lib/ai-search/topic-matcher";
import { EVENT_LIST_SELECT, EventsDataError } from "@/lib/data/events";
import { getSeoTopicLanding } from "@/lib/seo-topics";
import { getSupabaseServerClient } from "@/lib/supabase/server";
import type { AiSearchIntent, AnalyticsEvent, MultiHorizonAnalyticsResult } from "@/types/ai-search";
import { ASSETS, HORIZONS, type Asset, type EventListItem } from "@/types/events";

const BATCH_SIZE = 1_000;
const MAX_CANDIDATES = 10_000;
const MIN_INDEXABLE_MATCHES = 5;

export interface TopicLandingData {
  matchedRecords: number;
  independentEvents: number;
  assetBreakdown: Record<Asset, number>;
  overview: MultiHorizonAnalyticsResult;
}

function toAnalyticsEvent(event: EventListItem): AnalyticsEvent {
  const reactionV2 = Object.fromEntries(ASSETS.map((asset) => [
    asset,
    Object.fromEntries(HORIZONS.map((horizon) => [
      horizon,
      event[`${asset.toLowerCase()}_${horizon}` as keyof EventListItem] as number | null,
    ])),
  ])) as AnalyticsEvent["reactionV2"];
  const sentiment = event.sentiment === "positive" || event.sentiment === "bullish"
    ? "positive"
    : event.sentiment === "negative" || event.sentiment === "bearish"
      ? "negative"
      : event.sentiment === "neutral" ? "neutral" : null;
  const importance = event.importance === null
    ? null
    : event.importance < 0.33 ? "low" : event.importance < 0.67 ? "medium" : "high";
  return {
    eventId: event.event_id,
    slug: event.slug,
    title: event.title,
    publishedAt: event.published_at,
    assets: event.related_assets,
    primaryAsset: event.primary_asset,
    category: event.category as AnalyticsEvent["category"],
    sourceClass: event.source_type,
    sentiment,
    importance,
    reactionV2,
  };
}

function overviewIntent(asset: Asset, topic: NonNullable<AiSearchIntent["topic"]>, category: AiSearchIntent["category"]): AiSearchIntent {
  return {
    intent: "aggregate", asset, dateFrom: null, dateTo: null, category, topic,
    actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
    amount: null, entity: null, assetRole: "any", sourceClass: null, sentiment: null,
    reactionSign: null, importance: null, horizon: null, metric: "mean", sort: "newest",
    groupBy: "none", comparison: null, limit: 50,
  };
}

export async function getTopicLandingData(slug: string): Promise<TopicLandingData | null> {
  const landing = getSeoTopicLanding(slug);
  if (!landing) return null;
  const client = getSupabaseServerClient();
  const candidates: EventListItem[] = [];

  for (let from = 0; from < MAX_CANDIDATES; from += BATCH_SIZE) {
    let request = client
      .from("events")
      .select(EVENT_LIST_SELECT)
      .textSearch("search_vector", landing.candidateQuery, { config: "english", type: "websearch" });
    if (landing.asset) request = request.contains("related_assets", [landing.asset]);
    if (landing.category) request = request.eq("category", landing.category);
    const { data, error } = await request
      .order("published_at", { ascending: false })
      .order("event_id", { ascending: false })
      .range(from, from + BATCH_SIZE - 1);
    if (error) throw new EventsDataError("Topic landing data is temporarily unavailable.");
    const batch = (data ?? []) as unknown as EventListItem[];
    candidates.push(...batch);
    if (batch.length < BATCH_SIZE) break;
  }
  if (candidates.length >= MAX_CANDIDATES) throw new EventsDataError("Topic landing query is too broad.");

  const titleMatches = candidates.filter((event) => matchesTopic(toAnalyticsEvent(event), landing.topic));
  if (titleMatches.length < MIN_INDEXABLE_MATCHES) return null;
  const assetBreakdown = Object.fromEntries(ASSETS.map((asset) => [
    asset,
    titleMatches.filter((event) => event.related_assets.includes(asset)).length,
  ])) as Record<Asset, number>;
  const overview = runMultiHorizonAnalytics(
    candidates.map(toAnalyticsEvent),
    overviewIntent(landing.summaryAsset, landing.topic, landing.category),
  );
  const matchedRecords = overview.topicFilter?.matchedSampleSize ?? titleMatches.length;
  if (matchedRecords < MIN_INDEXABLE_MATCHES) return null;
  return {
    matchedRecords,
    independentEvents: overview.topicFilter?.independentEventCount ?? matchedRecords,
    assetBreakdown,
    overview,
  };
}
