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

export const AI_TOPICS = [
  "sec",
  "sec_filings",
  "regulatory_approval",
  "regulatory_enforcement",
  "etf",
  "etf_approval",
  "etf_rejection",
  "etf_delay",
  "hack",
  "listing",
  "lawsuit",
  "macro",
  "fed",
  "fed_rate_hike",
  "fed_rate_cut",
  "cpi",
  "upgrade",
  "staking",
  "large_investment",
  "institutional_purchase",
  "institutional_selling",
  "capital_inflow",
  "capital_outflow",
  "funding",
  "acquisition",
  "liquidation",
  "etf_inflow",
  "etf_outflow",
] as const;
export type AiTopic = (typeof AI_TOPICS)[number];

export const AI_TOPIC_LABELS: Record<AiTopic, string> = {
  sec: "SEC actions",
  sec_filings: "SEC filings",
  regulatory_approval: "Regulatory approvals",
  regulatory_enforcement: "Regulatory enforcement",
  etf: "ETF",
  etf_approval: "ETF approvals",
  etf_rejection: "ETF rejections",
  etf_delay: "Delayed ETF decisions",
  hack: "Hacks and exploits",
  listing: "Listings",
  lawsuit: "Lawsuits",
  macro: "Macro",
  fed: "Federal Reserve",
  fed_rate_hike: "Federal Reserve rate hikes",
  fed_rate_cut: "Federal Reserve rate cuts",
  cpi: "CPI",
  upgrade: "Protocol upgrades",
  staking: "Staking",
  large_investment: "Large investments",
  institutional_purchase: "Institutional purchases",
  institutional_selling: "Institutional selling",
  capital_inflow: "Capital inflows",
  capital_outflow: "Capital outflows",
  funding: "Funding",
  acquisition: "Acquisitions",
  liquidation: "Liquidations",
  etf_inflow: "ETF inflows",
  etf_outflow: "ETF outflows",
};

export const AI_ACTOR_TYPES = [
  "company", "fund", "ETF", "institution", "government", "regulator", "exchange",
  "protocol", "investor", "whale", "unknown",
] as const;
export type AiActorType = (typeof AI_ACTOR_TYPES)[number];

export const AI_ACTIONS = [
  "buy", "sell", "invest", "divest", "fund", "raise", "acquire", "liquidate", "deposit",
  "withdraw", "approve", "reject", "file", "sue", "hack", "exploit", "list", "delist",
  "upgrade", "stake", "unstake",
] as const;
export type AiAction = (typeof AI_ACTIONS)[number];

export const AI_DIRECTIONS = ["inflow", "outflow", "neutral", "unknown"] as const;
export type AiDirection = (typeof AI_DIRECTIONS)[number];

export const AI_MAGNITUDES = ["large", "standard", "unknown"] as const;
export type AiMagnitude = (typeof AI_MAGNITUDES)[number];

export const AI_ASSET_ROLES = ["primary", "secondary", "any"] as const;
export type AiAssetRole = (typeof AI_ASSET_ROLES)[number];

export const AI_AMOUNT_CURRENCIES = ["USD", "EUR"] as const;
export type AiAmountCurrency = (typeof AI_AMOUNT_CURRENCIES)[number];

export interface AiIntentAmount {
  currency: AiAmountCurrency;
  value: number;
}

export const AI_REACTION_SIGNS = ["positive", "negative"] as const;
export type AiReactionSign = (typeof AI_REACTION_SIGNS)[number];

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
  topic: AiTopic | null;
  actorType: AiActorType;
  action: AiAction | null;
  direction: AiDirection;
  magnitude: AiMagnitude;
  amount: AiIntentAmount | null;
  entity: string | null;
  assetRole: AiAssetRole;
  sourceClass: SourceType | null;
  sentiment: AiSentiment | null;
  reactionSign: AiReactionSign | null;
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
  primaryAsset?: Asset | null;
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
  relevanceConfidence?: number;
  assetRole?: Exclude<AiAssetRole, "any"> | "unknown";
  groupSize?: number;
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
  standardDeviation: number | null;
  standardError: number | null;
  trimmedMean5Percent: number | null;
  unit: "percent";
  citations: AiCitation[];
}

export interface ShareAnalyticsResult {
  kind: "share";
  positivePercent: number | null;
  negativePercent: number | null;
  neutralPercent: number | null;
  sampleSize: number;
  positive95Ci: { low: number; high: number } | null;
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
    standardDeviation: number | null;
    standardError: number | null;
    trimmedMean5Percent: number | null;
    positive95Ci: { low: number; high: number } | null;
  }>;
  citations: AiCitation[];
  topicFilter?: TopicFilterSummary;
}

export interface TopicFilterSummary {
  topic: AiTopic;
  broadSampleSize: number;
  matchedSampleSize: number;
  independentEventCount: number;
  duplicateGroupCount: number;
  largestDuplicateGroup: number;
  largestEntity: string | null;
  largestEntityShare: number;
  entityConcentrationWarning: boolean;
  confidenceThreshold: 0.6;
  heuristicMatches: number;
}

type CoreAnalyticsResult =
  | SearchAnalyticsResult
  | CountAnalyticsResult
  | ScalarAnalyticsResult
  | ShareAnalyticsResult
  | RankingAnalyticsResult
  | ComparisonAnalyticsResult
  | MultiHorizonAnalyticsResult;

export type AnalyticsResult = CoreAnalyticsResult & {
  topicFilter?: TopicFilterSummary;
};

export interface AiSearchSuccess {
  status: "ok";
  mode: "database";
  modeLabel: "Historical database analysis";
  language: "en" | "uk";
  basedOn: "Reaction V2";
  intent: AiSearchIntent;
  answer: string;
  calculation: string;
  result: AnalyticsResult;
  citations: AiCitation[];
  disclaimer: string;
}

export interface AiGeneralSuccess {
  status: "ok";
  mode: "general";
  modeLabel: "General AI explanation — no live sources";
  language: "en" | "uk";
  answer: string;
  citations: [];
  disclaimer: string;
}

export interface AiHybridSuccess extends Omit<AiSearchSuccess, "mode" | "modeLabel"> {
  mode: "hybrid";
  modeLabel: "Combined answer: general explanation + Reaction V2";
  generalExplanation: string;
}

export type AiResearchSuccess = AiSearchSuccess | AiGeneralSuccess | AiHybridSuccess;

export interface AiSearchErrorBody {
  status: "error" | "clarification" | "refusal" | "live_unsupported";
  code: string;
  message: string;
}
