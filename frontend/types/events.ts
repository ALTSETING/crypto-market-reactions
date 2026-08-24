export const ASSETS = ["BTC", "ETH", "SOL"] as const;
export type Asset = (typeof ASSETS)[number];

export const HORIZONS = ["1m", "5m", "15m", "1h", "4h", "24h"] as const;
export type Horizon = (typeof HORIZONS)[number];
export const REACTION_HORIZONS = [...HORIZONS, "average"] as const;
export type ReactionHorizon = (typeof REACTION_HORIZONS)[number];

export const EVENT_SORTS = ["newest", "oldest", "growth", "decline"] as const;
export type EventSort = (typeof EVENT_SORTS)[number];

export type ReactionValues = Record<Horizon, number | null>;

export interface EventListItem {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  source: string;
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
