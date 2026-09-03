import type { AiTopic, TopicFilterSummary } from "@/types/ai-search";
import type { Asset, EventCategory, Horizon, SourceType } from "@/types/events";

export const API_VERSION = "v1" as const;
export const API_BASE_PATH = "/api/v1" as const;
export const API_DEFAULT_LIMIT = 50;
export const API_MAX_LIMIT = 100;
export const API_MAX_TOPIC_SCAN_ROWS = 10_000;
export const API_DIRECTIONS = ["positive", "negative"] as const;

export type ApiDirection = (typeof API_DIRECTIONS)[number];

export interface ApiCursor {
  publishedAt: string;
  id: string;
}

export interface EventsApiQuery {
  asset: Asset | null;
  topic: AiTopic | null;
  category: EventCategory | null;
  sourceClass: SourceType | null;
  dateFrom: string | null;
  dateTo: string | null;
  search: string;
  limit: number;
  cursor: string | null;
}

export interface ReactionsApiQuery {
  asset: Asset;
  topic: AiTopic | null;
  horizon: Horizon | null;
  dateFrom: string | null;
  dateTo: string | null;
  direction: ApiDirection | null;
}

export type PublicReactionValues = Record<Asset, Record<Horizon, number | null>>;

export interface PublicEvent {
  id: string;
  slug: string;
  title: string;
  publishedAt: string;
  source: string;
  sourceUrl?: string;
  primaryAsset: Asset | null;
  relatedAssets: Asset[];
  category: EventCategory;
  sourceClass: SourceType;
  topic?: AiTopic;
  reactionV2: PublicReactionValues;
}

export interface EventsApiPage {
  data: PublicEvent[];
  pagination: {
    nextCursor: string | null;
    hasMore: boolean;
  };
}

export interface ReactionApiRow {
  horizon: Horizon;
  matchedArticles: number;
  independentEvents: number;
  mean: number | null;
  median: number | null;
  positivePercent: number | null;
  negativePercent: number | null;
  sampleSize: number;
}

export interface ReactionPipelineRow extends ReactionApiRow {
  topicFilter?: TopicFilterSummary;
}

