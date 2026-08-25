import type { Asset, EventCategory, Horizon, SourceType } from "@/types/events";

export const AI_INTENTS = ["search", "count", "aggregate", "rank", "compare"] as const;
export type AiIntentName = (typeof AI_INTENTS)[number];

export const AI_METRICS = ["events", "count", "mean", "median", "sign_share", "reaction"] as const;
export type AiMetric = (typeof AI_METRICS)[number];

export const AI_SORTS = ["newest", "oldest", "gainers", "losers"] as const;
export type AiSort = (typeof AI_SORTS)[number];

export const AI_IMPORTANCE = ["low", "medium", "high"] as const;
export type AiImportance = (typeof AI_IMPORTANCE)[number];

export const AI_SENTIMENTS = ["positive", "neutral", "negative"] as const;
export type AiSentiment = (typeof AI_SENTIMENTS)[number];

export interface AiComparison {
  field: "sourceClass";
  left: SourceType;
  right: SourceType;
}

export interface AiSearchIntent {
  intent: AiIntentName;
  asset: Asset | null;
  dateFrom: string | null;
  dateTo: string | null;
  category: EventCategory | null;
  sourceClass: SourceType | null;
  sentiment: AiSentiment | null;
  importance: AiImportance | null;
  horizon: Horizon | null;
  metric: AiMetric;
  sort: AiSort;
  groupBy: "none" | "source_class";
  comparison: AiComparison | null;
  limit: number;
}

export type IntentResolution =
  | { status: "ready"; intent: AiSearchIntent }
  | { status: "clarification"; message: string }
  | { status: "rejected"; message: string };

export interface AnalyticsEvent {
  eventId: string;
  slug: string;
  title: string;
  publishedAt: string;
  assets: Asset[];
  category: EventCategory;
  sourceClass: SourceType;
  sentiment: AiSentiment | null;
  importance: AiImportance | null;
  reactionV2: Record<Asset, Record<Horizon, number | null>>;
}

export interface AiCitation {
  eventId: string;
  title: string;
  href: string;
}

export interface SearchAnalyticsResult {
  kind: "search";
  matched: number;
  returned: number;
  citations: AiCitation[];
}

export interface CountAnalyticsResult {
  kind: "count";
  value: number;
  sampleSize: number;
  citations: AiCitation[];
}

export interface ScalarAnalyticsResult {
  kind: "scalar";
  metric: "mean" | "median";
  value: number | null;
  sampleSize: number;
  unit: "percent";
  citations: AiCitation[];
}

export interface ShareAnalyticsResult {
  kind: "share";
  positivePercent: number | null;
  negativePercent: number | null;
  neutralPercent: number | null;
  sampleSize: number;
  unit: "percent";
  citations: AiCitation[];
}

export interface RankingAnalyticsResult {
  kind: "ranking";
  direction: "gainers" | "losers";
  sampleSize: number;
  items: Array<AiCitation & { reaction: number }>;
  unit: "percent";
  citations: AiCitation[];
}

export interface ComparisonAnalyticsResult {
  kind: "comparison";
  metric: "mean" | "median";
  left: { sourceClass: SourceType; value: number | null; sampleSize: number };
  right: { sourceClass: SourceType; value: number | null; sampleSize: number };
  difference: number | null;
  unit: "percentage_points";
  citations: AiCitation[];
}

export interface MultiHorizonAnalyticsResult {
  kind: "multi_horizon";
  rows: Array<{
    horizon: Horizon;
    mean: number | null;
    median: number | null;
    positivePercent: number | null;
    sampleSize: number;
  }>;
  citations: AiCitation[];
}

export type AnalyticsResult =
  | SearchAnalyticsResult
  | CountAnalyticsResult
  | ScalarAnalyticsResult
  | ShareAnalyticsResult
  | RankingAnalyticsResult
  | ComparisonAnalyticsResult
  | MultiHorizonAnalyticsResult;

export interface AiSearchSuccess {
  status: "ok";
  basedOn: "Reaction V2";
  intent: AiSearchIntent;
  answer: string;
  calculation: string;
  result: AnalyticsResult;
  citations: AiCitation[];
  disclaimer: string;
}

export interface AiSearchErrorBody {
  status: "error" | "clarification" | "rejected";
  code: string;
  message: string;
}
