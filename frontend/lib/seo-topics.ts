import type { AiTopic } from "@/types/ai-search";
import type { Asset, EventCategory } from "@/types/events";

export interface SeoTopicLanding {
  slug: string;
  name: string;
  seoTitle: string;
  description: string;
  intro: string;
  topic: AiTopic;
  candidateQuery: string;
  asset: Asset | null;
  summaryAsset: Asset;
  category: EventCategory | null;
}

export const SEO_TOPIC_LANDINGS: readonly SeoTopicLanding[] = [
  {
    slug: "bitcoin-etf",
    name: "Bitcoin ETF Events",
    seoTitle: "Bitcoin ETF Events & BTC Reactions | Crypto Market Reactions",
    description: "Explore historical Bitcoin ETF events and deterministic BTC reactions from one minute through twenty-four hours after publication.",
    intro: "This archive groups Bitcoin ETF announcements, filings, approvals, delays and related coverage that explicitly mention an ETF and Bitcoin.",
    topic: "etf",
    candidateQuery: "ETF",
    asset: "BTC",
    summaryAsset: "BTC",
    category: null,
  },
  {
    slug: "ethereum-etf",
    name: "Ethereum ETF Events",
    seoTitle: "Ethereum ETF Events & ETH Reactions | Crypto Market Reactions",
    description: "Explore historical Ethereum ETF events and deterministic ETH reactions from one minute through twenty-four hours after publication.",
    intro: "This archive groups Ethereum ETF announcements, filings, approvals, delays and related coverage that explicitly mention an ETF and Ethereum.",
    topic: "etf",
    candidateQuery: "ETF",
    asset: "ETH",
    summaryAsset: "ETH",
    category: null,
  },
  {
    slug: "sec-enforcement",
    name: "SEC Enforcement and Crypto",
    seoTitle: "SEC Crypto Enforcement Reactions | Crypto Market Reactions",
    description: "Review historical crypto market reactions after SEC enforcement actions, lawsuits, charges and penalties found in the event archive.",
    intro: "This landing page includes archived headlines where SEC or regulator context is explicitly connected to enforcement, charges, penalties or litigation.",
    topic: "regulatory_enforcement",
    candidateQuery: "SEC",
    asset: null,
    summaryAsset: "BTC",
    category: null,
  },
  {
    slug: "crypto-hacks",
    name: "Crypto Hacks and Exploits",
    seoTitle: "Crypto Hack Reactions for BTC, ETH & SOL | Market History",
    description: "Study historical BTC, ETH and SOL reactions after archived crypto hacks, exploits, security breaches and cyberattacks.",
    intro: "This archive groups event titles that explicitly describe a hack, exploit, security breach or cyberattack; it does not infer unreported incidents.",
    topic: "hack",
    candidateQuery: "hack OR exploit OR breach",
    asset: null,
    summaryAsset: "ETH",
    category: null,
  },
  {
    slug: "institutional-buying",
    name: "Institutional Crypto Buying",
    seoTitle: "Institutional Crypto Buying Reactions | Historical Data",
    description: "Explore historical crypto reactions after explicitly reported institutional purchases, treasury buys and other large professional buying events.",
    intro: "This page groups archived reports that explicitly describe institutional or treasury buying. General adoption stories without a purchase are excluded.",
    topic: "institutional_purchase",
    candidateQuery: "institutional OR treasury",
    asset: null,
    summaryAsset: "BTC",
    category: null,
  },
  {
    slug: "etf-inflows",
    name: "Crypto ETF Inflows",
    seoTitle: "Crypto ETF Inflows & Historical Reactions | BTC and ETH",
    description: "See historical BTC and ETH market reactions around archived crypto ETF inflow reports, with deterministic Reaction V2 horizons.",
    intro: "This landing page includes archived event titles that explicitly connect crypto ETFs with reported inflows. Generic ETF news is excluded.",
    topic: "etf_inflow",
    candidateQuery: "ETF",
    asset: null,
    summaryAsset: "BTC",
    category: null,
  },
  {
    slug: "etf-outflows",
    name: "Crypto ETF Outflows",
    seoTitle: "Crypto ETF Outflows & Historical Reactions | BTC and ETH",
    description: "See historical BTC and ETH market reactions around archived crypto ETF outflow reports, with deterministic Reaction V2 horizons.",
    intro: "This landing page includes archived event titles that explicitly connect crypto ETFs with reported outflows. Generic ETF news is excluded.",
    topic: "etf_outflow",
    candidateQuery: "ETF",
    asset: null,
    summaryAsset: "BTC",
    category: null,
  },
  {
    slug: "fed-rate-decisions",
    name: "Federal Reserve Rate Decisions",
    seoTitle: "Crypto Reactions to Fed Rate Decisions | Historical Data",
    description: "Review historical crypto market reactions around Federal Reserve and FOMC rate decisions recorded in the event archive.",
    intro: "This page groups archived macro event titles that explicitly mention the Federal Reserve, Fed or FOMC. Reaction V2 shows association, not causation.",
    topic: "fed",
    candidateQuery: "Fed OR FOMC OR \"Federal Reserve\"",
    asset: null,
    summaryAsset: "BTC",
    category: "macro",
  },
] as const;

export function getSeoTopicLanding(slug: string): SeoTopicLanding | null {
  return SEO_TOPIC_LANDINGS.find((topic) => topic.slug === slug) ?? null;
}
