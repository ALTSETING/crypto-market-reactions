import type { Asset } from "@/types/events";

export const SITE_NAME = "Crypto Market Reactions";
export const HOME_TITLE = "Crypto Market Reactions — Historical BTC, ETH & SOL Event Analysis";
export const HOME_DESCRIPTION = "See how Bitcoin, Ethereum and Solana reacted after ETFs, SEC actions, hacks, institutional flows and other crypto events using historical Reaction V2 data.";
export const EVENTS_TITLE = "Historical Crypto Events — BTC, ETH & SOL Reactions";
export const EVENTS_DESCRIPTION = "Search the historical crypto event archive and inspect Reaction V2 returns for Bitcoin, Ethereum and Solana from one minute through twenty-four hours.";
export const AI_TITLE = "AI Crypto Research — Historical Market Reactions";
export const AI_DESCRIPTION = "Ask research questions about historical BTC, ETH and SOL events using cited archive evidence and deterministic Reaction V2 statistics.";

type SiteEnvironment = { SITE_URL?: string; VERCEL_PROJECT_PRODUCTION_URL?: string };

export interface SeoEventData {
  slug: string;
  title: string;
  published_at: string;
  source: string;
  primary_asset: Asset | null;
  related_assets: Asset[];
}

export interface BreadcrumbItem { name: string; path: string }

interface WebPageStructuredDataOptions {
  name: string;
  description: string;
  path: string;
  breadcrumbs: BreadcrumbItem[];
  datePublished?: string;
  citation?: string | null;
  about?: string[];
}

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function trimAtWord(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  if (maximum <= 1) return "…";
  const candidate = value.slice(0, maximum - 1);
  const lastSpace = candidate.lastIndexOf(" ");
  const safe = lastSpace >= Math.floor(maximum * 0.55) ? candidate.slice(0, lastSpace) : candidate;
  return `${safe.replace(/[\s,;:—-]+$/u, "")}…`;
}

function trimMiddle(value: string, maximum: number): string {
  if (value.length <= maximum) return value;
  const available = maximum - 1;
  const startLength = Math.ceil(available * 0.58);
  const endLength = available - startLength;
  return `${value.slice(0, startLength).trimEnd()}…${value.slice(-endLength).trimStart()}`;
}

function eventAssets(event: SeoEventData): Asset[] {
  if (event.related_assets.length > 0) return event.related_assets;
  return event.primary_asset ? [event.primary_asset] : [];
}

function reactionLabel(event: SeoEventData): string {
  const assets = eventAssets(event);
  if (assets.length === 0) return "Crypto Reaction";
  return `${event.primary_asset ?? assets[0]} Reaction`;
}

function assetNames(event: SeoEventData): string {
  const names: Record<Asset, string> = { BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana" };
  const assets = eventAssets(event).map((asset) => names[asset]);
  if (assets.length === 0) return "the crypto market";
  if (assets.length === 1) return assets[0];
  if (assets.length === 2) return `${assets[0]} and ${assets[1]}`;
  return `${assets.slice(0, -1).join(", ")} and ${assets.at(-1)}`;
}

export function resolveSiteUrl(environment: SiteEnvironment = process.env as SiteEnvironment): URL {
  const configured = environment.SITE_URL?.trim();
  const vercelProductionDomain = environment.VERCEL_PROJECT_PRODUCTION_URL?.trim();
  const candidate = configured || (vercelProductionDomain ? `https://${vercelProductionDomain}` : "http://localhost:3000");
  let parsed: URL;
  try { parsed = new URL(candidate); } catch { throw new Error("SITE_URL must be an absolute HTTP or HTTPS URL."); }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("SITE_URL must use HTTP or HTTPS.");
  if (parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error("SITE_URL must not include credentials, query parameters, or a fragment.");
  parsed.pathname = parsed.pathname.replace(/\/+$/, "") || "/";
  return parsed;
}

export function siteUrl(pathname = "/", environment?: SiteEnvironment): string {
  return new URL(pathname.replace(/^\/+/, ""), resolveSiteUrl(environment)).toString();
}

export function buildEventSeoTitle(event: SeoEventData): string {
  const date = Number.isNaN(new Date(event.published_at).valueOf()) ? "Historical" : new Date(event.published_at).toISOString().slice(0, 10);
  const prefix = `${reactionLabel(event)} to `;
  const suffix = ` — ${date} | ${SITE_NAME}`;
  const original = normalizeWhitespace(event.title) || "Historical crypto event";
  const topicBudget = Math.max(4, 65 - prefix.length - suffix.length);
  return `${prefix}${trimMiddle(original, topicBudget)}${suffix}`;
}

export function buildEventSeoDescription(event: SeoEventData): string {
  const date = Number.isNaN(new Date(event.published_at).valueOf()) ? "the recorded publication date" : new Date(event.published_at).toISOString().slice(0, 10);
  const source = trimAtWord(normalizeWhitespace(event.source) || "the original source", 26);
  const prefix = `On ${date}, ${source} reported “`;
  const suffix = `”. See how ${assetNames(event)} reacted at six Reaction V2 horizons from 1m to 24h.`;
  const title = trimAtWord(normalizeWhitespace(event.title) || "this historical crypto event", Math.max(24, 166 - prefix.length - suffix.length));
  let description = `${prefix}${title}${suffix}`;
  if (description.length < 140) description += " Missing values are not estimated.";
  return trimAtWord(description, 170);
}

export function buildWebsiteStructuredData() {
  return { "@context": "https://schema.org", "@type": "WebSite", name: SITE_NAME, url: siteUrl("/"), description: HOME_DESCRIPTION };
}

export function buildWebPageStructuredData(options: WebPageStructuredDataOptions) {
  const pageUrl = siteUrl(options.path);
  const webPage: Record<string, unknown> = {
    "@type": "WebPage", "@id": `${pageUrl}#webpage`, url: pageUrl, name: options.name, description: options.description,
    isPartOf: { "@type": "WebSite", name: SITE_NAME, url: siteUrl("/") },
  };
  if (options.datePublished) webPage.datePublished = options.datePublished;
  if (options.citation) webPage.citation = options.citation;
  if (options.about?.length) webPage.about = options.about.map((name) => ({ "@type": "Thing", name }));
  return {
    "@context": "https://schema.org",
    "@graph": [webPage, {
      "@type": "BreadcrumbList",
      itemListElement: options.breadcrumbs.map((item, index) => ({ "@type": "ListItem", position: index + 1, name: item.name, item: siteUrl(item.path) })),
    }],
  };
}
