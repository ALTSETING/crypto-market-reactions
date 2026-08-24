export const ASSETS = ["BTC", "ETH", "SOL"] as const;
export type Asset = (typeof ASSETS)[number];

export const HORIZONS = ["1m", "5m", "15m", "1h", "4h", "24h"] as const;
export type Horizon = (typeof HORIZONS)[number];
export const REACTION_HORIZONS = [...HORIZONS, "average"] as const;
export type ReactionHorizon = (typeof REACTION_HORIZONS)[number];

export const EVENT_SORTS = ["newest", "oldest", "growth", "decline"] as const;
export type EventSort = (typeof EVENT_SORTS)[number];

export const SOURCE_TYPES = [
  "news_media",
  "primary_document",
  "official_announcement",
  "unknown",
] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];

export const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  news_media: "News media",
  primary_document: "Primary document",
  official_announcement: "Official announcement",
  unknown: "Unknown source type",
};

export const EVENT_CATEGORIES = [
  "defi", "etf", "exchange", "fees", "hack", "institutional",
  "institutional_adoption", "layer2", "legal", "legal_action", "macro",
  "market_commentary", "network_activity", "news", "nft", "official_decision",
  "other", "partnership", "policy_statement", "product_launch", "protocol_update",
  "protocol_upgrade", "regulation", "security", "security_event", "stablecoins",
  "staking", "tokenomics",
] as const;
export type EventCategory = (typeof EVENT_CATEGORIES)[number];

export const EVENT_YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026] as const;
export type EventYear = (typeof EVENT_YEARS)[number];

export type ReactionValues = Record<Horizon, number | null>;

export interface EventListItem {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  source: string;
  source_type: SourceType;
  primary_asset: Asset | null;
  related_assets: Asset[];
  category: string;
  sentiment: string | null;
  importance: number | null;
  btc_1m: number | null;
  btc_5m: number | null;
  btc_15m: number | null;
  btc_1h: number | null;
  btc_4h: number | null;
  btc_24h: number | null;
  btc_average_reaction: number | null;
  eth_1m: number | null;
  eth_5m: number | null;
  eth_15m: number | null;
  eth_1h: number | null;
  eth_4h: number | null;
  eth_24h: number | null;
  eth_average_reaction: number | null;
  sol_1m: number | null;
  sol_5m: number | null;
  sol_15m: number | null;
  sol_1h: number | null;
  sol_4h: number | null;
  sol_24h: number | null;
  sol_average_reaction: number | null;
}

export interface EventDetail extends EventListItem {
  source_url: string;
  sentiment_score: number | null;
  reaction_methodology: string;
  reaction_value_unit: "percent";
  btc_reaction_source: string | null;
  btc_reference_time: string | null;
  btc_reference_latency_minutes: number | null;
  eth_reaction_source: string | null;
  eth_reference_time: string | null;
  eth_reference_latency_minutes: number | null;
  sol_reaction_source: string | null;
  sol_reference_time: string | null;
  sol_reference_latency_minutes: number | null;
}

export interface EventsQuery {
  query: string;
  asset: Asset | null;
  source: string;
  sourceType: SourceType | null;
  category: EventCategory | null;
  year: EventYear | null;
  from: string | null;
  to: string | null;
  sort: EventSort;
  horizon: ReactionHorizon;
  marketDataOnly: boolean;
  page: number;
  pageSize: number;
}

export interface EventsPage {
  items: EventListItem[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface SitemapEvent {
  slug: string;
  updated_at: string;
}

export interface DatasetStats {
  events: number;
  firstYear: number;
  lastYear: number;
  eventsByYear: Array<{ year: number; events: number }>;
}

export interface ApiErrorBody {
  error: string;
  code: string;
}
