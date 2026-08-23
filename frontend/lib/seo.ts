import type { Asset } from "@/types/events";

export const SITE_NAME = "Crypto Market Reaction Database";
export const HOME_TITLE =
  "Crypto Market Reaction Database — Historical BTC & ETH News Reactions";
export const HOME_DESCRIPTION =
  "Search thousands of historical crypto events and inspect how Bitcoin, Ethereum and Solana reacted from 1 minute to 24 hours after publication.";

type SiteEnvironment = {
  SITE_URL?: string;
  VERCEL_PROJECT_PRODUCTION_URL?: string;
};

export interface SeoEventData {
  slug: string;
  title: string;
  published_at: string;
  source: string;
  primary_asset: Asset | null;
  related_assets: Asset[];
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
  if (assets.length === 0) return "Crypto Price Reaction";
  if (assets.length === 1) return `${assets[0]} Price Reaction`;
  return `${assets.slice(0, 2).join(" & ")} Price Reaction`;
}

function assetNames(event: SeoEventData): string {
  const names: Record<Asset, string> = {
    BTC: "Bitcoin",
    ETH: "Ethereum",
    SOL: "Solana",
  };
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
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error("SITE_URL must be an absolute HTTP or HTTPS URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("SITE_URL must use HTTP or HTTPS.");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("SITE_URL must not include credentials, query parameters, or a fragment.");
  }
  parsed.pathname = parsed.pathname.replace(/\/+$/, "") || "/";
  return parsed;
}

export function siteUrl(pathname = "/", environment?: SiteEnvironment): string {
  return new URL(pathname.replace(/^\/+/, ""), resolveSiteUrl(environment)).toString();
}

export function buildEventSeoTitle(event: SeoEventData): string {
  const date = Number.isNaN(new Date(event.published_at).valueOf())
    ? "Historical"
    : new Date(event.published_at).toISOString().slice(0, 10);
  const suffix = ` — ${reactionLabel(event)} · ${date}`;
  const original = normalizeWhitespace(event.title) || "Historical crypto event";
  const initialBudget = Math.max(12, 65 - suffix.length);
  const disambiguator = original.length > initialBudget ? ` · ${event.slug.slice(-8)}` : "";
  const titleBudget = Math.max(12, 65 - suffix.length - disambiguator.length);
  return `${trimMiddle(original, titleBudget)}${disambiguator}${suffix}`;
}

export function buildEventSeoDescription(event: SeoEventData): string {
  const source = trimAtWord(normalizeWhitespace(event.source) || "the original source", 28);
  const prefix = `See how ${assetNames(event)} reacted after “`;
  const suffix = `”, an event from ${source}. Explore verified returns at 1m, 5m, 15m, 1h, 4h and 24h.`;
  const title = trimAtWord(normalizeWhitespace(event.title) || "this historical crypto event", Math.max(28, 166 - prefix.length - suffix.length));
  let description = `${prefix}${title}${suffix}`;
  if (description.length < 140) description += " Missing values are not estimated.";
  return trimAtWord(description, 170);
}
