import type { AiSearchIntent, AnalyticsEvent } from "@/types/ai-search";
import type { SemanticEventMatch } from "@/lib/ai-search/semantic-matcher";

export interface IndependentEventGroup {
  representative: AnalyticsEvent;
  members: AnalyticsEvent[];
  entity: string | null;
}

export interface IndependentEventSample {
  representatives: AnalyticsEvent[];
  groups: IndependentEventGroup[];
  groupSizeByRepresentativeId: Map<string, number>;
  duplicateGroupCount: number;
  largestGroupSize: number;
  largestEntity: string | null;
  largestEntityShare: number;
}

const SOURCE_PRIORITY: Record<AnalyticsEvent["sourceClass"], number> = {
  primary_document: 0,
  official_announcement: 1,
  news_media: 2,
  unknown: 3,
};

const ENTITY_ALIASES: ReadonlyArray<readonly [string, RegExp]> = [
  ["bitmine", /\b(?:bitmine|bmnr)\b/iu],
  ["sharplink", /\b(?:sharplink|sbet)\b/iu],
  ["blackrock", /\b(?:blackrock|ibit|ishares)\b/iu],
  ["fidelity", /\b(?:fidelity|fbtc)\b/iu],
  ["grayscale", /\b(?:grayscale|gbtc|ethe)\b/iu],
  ["wisdomtree", /\bwisdomtree\b/iu],
  ["vaneck", /\bvan\s*eck\b/iu],
  ["ark-invest", /\b(?:ark\s+invest|ark\s*21shares|arkb)\b/iu],
  ["bitwise", /\bbitwise\b/iu],
  ["morgan-stanley", /\bmorgan\s+stanley\b/iu],
  ["drift", /\bdrift\b/iu],
  ["swissborg", /\bswissborg\b/iu],
  ["nomad", /\bnomad\b/iu],
  ["slope", /\bslope\b/iu],
  ["cashio", /\bcashio\b/iu],
  ["taiko", /\btaiko\b/iu],
  ["kelp-dao", /\bkelp(?:\s+dao)?\b/iu],
  ["arbitrum", /\barbitrum\b/iu],
  ["aave", /\baave\b/iu],
  ["binance", /\bbinance\b/iu],
  ["coinbase", /\bcoinbase\b/iu],
  ["deribit", /\bderibit\b/iu],
  ["kucoin", /\bkucoin\b/iu],
  ["strategy", /\b(?:microstrategy|strategy)\b/iu],
  ["coinshares", /\bcoinshares\b/iu],
  ["first-trust-skybridge", /\b(?:first\s+trust|skybridge)\b/iu],
  ["sec", /\b(?:sec|securities and exchange commission)\b/iu],
  ["cftc", /\bcftc\b/iu],
  ["federal-reserve", /\b(?:federal reserve|fed|fomc)\b/iu],
];

const STOP_WORDS = new Set([
  "a", "an", "and", "as", "at", "after", "amid", "are", "be", "by", "for", "from", "has", "have", "in", "into", "is", "it", "its",
  "latest", "major", "more", "new", "news", "of", "on", "over", "report", "reports", "says", "the", "to", "with",
  "bitcoin", "btc", "ethereum", "ether", "eth", "solana", "sol", "crypto", "cryptocurrency", "cryptocurrencies",
]);

const GENERIC_ENTITY_WORDS = new Set([
  ...STOP_WORDS,
  "approval", "approves", "buys", "cuts", "etf", "etfs", "exchange", "files", "fund", "funds", "hack", "hacked", "hike", "inflows",
  "launches", "outflows", "purchase", "purchases", "rate", "rates", "regulator", "rejects", "sales", "sells", "spot", "update",
]);

function normalizedWords(title: string): string[] {
  return title
    .normalize("NFKD")
    .toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/u)
    .filter((word) => word.length > 2 && !STOP_WORDS.has(word) && !/^\d+$/u.test(word))
    .map((word) => {
      if (/^(?:hack|hacks|hacked|exploit|exploits|exploited|breach)$/u.test(word)) return "securityincident";
      if (/^(?:buy|buys|buying|bought|purchase|purchases|purchased|adds|added)$/u.test(word)) return "buy";
      if (/^(?:sell|sells|selling|sold|sale|sales|offload|offloaded)$/u.test(word)) return "sell";
      if (/^(?:inflow|inflows|deposit|deposits)$/u.test(word)) return "inflow";
      if (/^(?:outflow|outflows|withdrawal|withdrawals|redemption|redemptions)$/u.test(word)) return "outflow";
      if (/^(?:approve|approves|approved|approval|approvals)$/u.test(word)) return "approve";
      if (/^(?:reject|rejects|rejected|rejection|rejections|denies|denied)$/u.test(word)) return "reject";
      if (/^(?:sue|sues|sued|lawsuit|lawsuits|enforcement|charge|charges|charged)$/u.test(word)) return "legalaction";
      if (/^(?:cut|cuts|cutting)$/u.test(word)) return "cut";
      if (/^(?:rate|rates)$/u.test(word)) return "rate";
      return word;
    });
}

function titleOverlap(left: string, right: string): { containment: number; jaccard: number } {
  const leftWords = new Set(normalizedWords(left));
  const rightWords = new Set(normalizedWords(right));
  if (leftWords.size === 0 || rightWords.size === 0) return { containment: 0, jaccard: 0 };
  const intersection = [...leftWords].filter((word) => rightWords.has(word)).length;
  return {
    containment: intersection / Math.min(leftWords.size, rightWords.size),
    jaccard: intersection / (leftWords.size + rightWords.size - intersection),
  };
}

function numericAnchors(title: string): Set<string> {
  const anchors = new Set<string>();
  const pattern = /(?:[$€£]\s*)?\d[\d,.]*(?:\.\d+)?\s*(?:k|m|bn|b|million|billion|trillion|%|bps?|basis points?|btc|bitcoin|eth|ether|sol|solana|usd|eur|gbp)(?=\W|$)/giu;
  for (const match of title.matchAll(pattern)) {
    anchors.add(match[0].toLocaleLowerCase("en-US").replace(/[\s,]/gu, "").replace(/million/gu, "m").replace(/billion|bn/gu, "b"));
  }
  return anchors;
}

function hasSharedAnchor(left: string, right: string): boolean {
  const leftAnchors = numericAnchors(left);
  if (leftAnchors.size === 0) return false;
  return [...numericAnchors(right)].some((anchor) => leftAnchors.has(anchor));
}

function hasConflictingAnchors(left: string, right: string): boolean {
  const leftAnchors = numericAnchors(left);
  const rightAnchors = numericAnchors(right);
  return leftAnchors.size > 0 && rightAnchors.size > 0 && ![...leftAnchors].some((anchor) => rightAnchors.has(anchor));
}

function inferEntity(title: string): string | null {
  for (const [entity, pattern] of ENTITY_ALIASES) {
    if (pattern.test(title)) return entity;
  }
  const prefix = title
    .replace(/^(?:bitcoin|ethereum|ether|solana|crypto)\s+news\s*:\s*/iu, "")
    .match(/^(.{2,64}?)\s+(?:adds?|announces?|approves?|buys?|cuts?|files?|freezes?|halts?|launches?|raises?|rejects?|repays?|restores?|sells?|sues?)(?:\s|$)/iu)?.[1];
  if (!prefix) return null;
  const words = prefix
    .replace(/[’']s\b/gu, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/u)
    .filter((word) => !GENERIC_ENTITY_WORDS.has(word.toLocaleLowerCase("en-US")));
  if (words.length === 0 || words.length > 4) return null;
  return words.join("-").toLocaleLowerCase("en-US");
}

function eventType(event: AnalyticsEvent, match: SemanticEventMatch | undefined, intent: AiSearchIntent): string {
  const action = match?.action ?? intent.action;
  if (action === "hack" || action === "exploit") return "security-incident";
  if (action) return action;
  const title = event.title;
  if (/\b(?:outflow|outflows|withdrawal|withdrawals|redemption|redemptions)\b/iu.test(title)) return "withdraw";
  if (/\b(?:inflow|inflows|deposit|deposits)\b/iu.test(title)) return "deposit";
  if (/\b(?:reject|rejects|rejected|denies|denied)\b/iu.test(title)) return "reject";
  if (/\b(?:approv|approved|approval|approves)\w*\b/iu.test(title)) return "approve";
  if (/\b(?:hack|hacked|exploit|exploited|breach)\b/iu.test(title)) return "security-incident";
  if (/\b(?:lawsuit|sues?|sued|charges?|charged|enforcement)\b/iu.test(title)) return "legal-action";
  if (/\b(?:minutes|meeting minutes)\b/iu.test(title)) return "macro-minutes";
  if (/\b(?:expect|expected|forecast|preview|ahead|bets?|odds|could|may)\b/iu.test(title)) return "forecast";
  if (/\b(?:rate cut|cuts? rates?|lower(?:s|ed)? rates?)\b/iu.test(title)) return "rate-cut";
  if (/\b(?:rate hike|hikes? rates?|raises? rates?)\b/iu.test(title)) return "rate-hike";
  if (/\b(?:cpi|consumer price index|inflation data|inflation report)\b/iu.test(title)) return "cpi-release";
  return intent.topic ?? event.category;
}

function hoursApart(left: AnalyticsEvent, right: AnalyticsEvent): number {
  return Math.abs(Date.parse(left.publishedAt) - Date.parse(right.publishedAt)) / 3_600_000;
}

function compatibleAssetContext(left: AnalyticsEvent, right: AnalyticsEvent): boolean {
  if (left.primaryAsset && right.primaryAsset && left.primaryAsset !== right.primaryAsset) return false;
  return left.assets.some((asset) => right.assets.includes(asset));
}

function sameConcreteEvent(
  left: AnalyticsEvent,
  right: AnalyticsEvent,
  intent: AiSearchIntent,
  semanticMatches: ReadonlyMap<string, SemanticEventMatch>,
): boolean {
  if (!compatibleAssetContext(left, right)) return false;
  if (eventType(left, semanticMatches.get(left.eventId), intent) !== eventType(right, semanticMatches.get(right.eventId), intent)) return false;

  const hours = hoursApart(left, right);
  if (!Number.isFinite(hours)) return false;
  const leftEntity = inferEntity(left.title);
  const rightEntity = inferEntity(right.title);
  const sameEntity = leftEntity !== null && leftEntity === rightEntity;
  const bothUnknown = leftEntity === null && rightEntity === null;
  const overlap = titleOverlap(left.title, right.title);
  const sharedAnchor = hasSharedAnchor(left.title, right.title);
  const conflictingAnchors = hasConflictingAnchors(left.title, right.title);
  const sameUtcDay = left.publishedAt.slice(0, 10) === right.publishedAt.slice(0, 10);

  if (["etf_inflow", "etf_outflow", "capital_inflow", "capital_outflow"].includes(intent.topic ?? "")) {
    return !conflictingAnchors && sameUtcDay && (sameEntity || bothUnknown) && (sharedAnchor || overlap.containment >= 0.78 || overlap.jaccard >= 0.64);
  }
  if (["institutional_purchase", "institutional_selling", "large_investment"].includes(intent.topic ?? "")) {
    return !conflictingAnchors && hours <= 48 && sameEntity && (sharedAnchor || overlap.containment >= 0.68 || overlap.jaccard >= 0.52);
  }
  if (intent.topic === "hack") {
    const explicitlyLinkedUpdate = /\b(?:after|following|linked to|related to|tied to|repays?|restores?|freezes?|halts?)\b/iu.test(`${left.title} ${right.title}`);
    return hours <= 24 * 14 && sameEntity && (sharedAnchor || explicitlyLinkedUpdate || overlap.containment >= 0.58 || overlap.jaccard >= 0.4);
  }
  if (["cpi", "fed", "fed_rate_hike", "fed_rate_cut", "macro"].includes(intent.topic ?? "")) {
    return hours <= 36 && sameUtcDay && (sameEntity || bothUnknown) && (sharedAnchor || overlap.containment >= 0.42 || overlap.jaccard >= 0.3);
  }
  if (["etf", "etf_approval", "etf_rejection", "etf_delay", "sec", "sec_filings", "regulatory_approval", "regulatory_enforcement", "lawsuit"].includes(intent.topic ?? "")) {
    return hours <= 72 && sameEntity && (sharedAnchor || overlap.containment >= 0.58 || overlap.jaccard >= 0.42);
  }
  return hours <= 24 && (sameEntity || bothUnknown) && (sharedAnchor || overlap.containment >= 0.82 || overlap.jaccard >= 0.7);
}

function representativeComparator(
  semanticMatches: ReadonlyMap<string, SemanticEventMatch>,
  left: AnalyticsEvent,
  right: AnalyticsEvent,
): number {
  return SOURCE_PRIORITY[left.sourceClass] - SOURCE_PRIORITY[right.sourceClass]
    || left.publishedAt.localeCompare(right.publishedAt)
    || (semanticMatches.get(right.eventId)?.relevanceScore ?? 0) - (semanticMatches.get(left.eventId)?.relevanceScore ?? 0)
    || left.eventId.localeCompare(right.eventId);
}

function groupEntity(members: readonly AnalyticsEvent[]): string | null {
  const counts = new Map<string, number>();
  for (const member of members) {
    const entity = inferEntity(member.title);
    if (entity) counts.set(entity, (counts.get(entity) ?? 0) + 1);
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0]?.[0] ?? null;
}

export function groupIndependentEvents(
  rankedMatches: readonly AnalyticsEvent[],
  intent: AiSearchIntent,
  semanticMatches: ReadonlyMap<string, SemanticEventMatch>,
): IndependentEventSample {
  if (!intent.topic) {
    const groups = rankedMatches.map((event) => ({ representative: event, members: [event], entity: inferEntity(event.title) }));
    return summarize(groups);
  }

  const groups: Array<{ members: AnalyticsEvent[]; rank: number }> = [];
  rankedMatches.forEach((event, rank) => {
    const existing = groups.find(({ members }) => members.every((member) => sameConcreteEvent(event, member, intent, semanticMatches)));
    if (existing) existing.members.push(event);
    else groups.push({ members: [event], rank });
  });

  const selected = groups
    .sort((left, right) => left.rank - right.rank)
    .map(({ members }) => ({
      representative: [...members].sort((left, right) => representativeComparator(semanticMatches, left, right))[0],
      members: [...members].sort((left, right) => left.publishedAt.localeCompare(right.publishedAt) || left.eventId.localeCompare(right.eventId)),
      entity: groupEntity(members),
    }));
  return summarize(selected);
}

function summarize(groups: IndependentEventGroup[]): IndependentEventSample {
  const entityCounts = new Map<string, number>();
  for (const group of groups) {
    if (group.entity) entityCounts.set(group.entity, (entityCounts.get(group.entity) ?? 0) + 1);
  }
  const largestEntityEntry = [...entityCounts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0];
  const largestEntityShare = groups.length === 0 || !largestEntityEntry ? 0 : Math.round(largestEntityEntry[1] * 10_000 / groups.length) / 100;
  return {
    representatives: groups.map(({ representative }) => representative),
    groups,
    groupSizeByRepresentativeId: new Map(groups.map(({ representative, members }) => [representative.eventId, members.length])),
    duplicateGroupCount: groups.filter(({ members }) => members.length > 1).length,
    largestGroupSize: Math.max(0, ...groups.map(({ members }) => members.length)),
    largestEntity: largestEntityEntry?.[0] ?? null,
    largestEntityShare,
  };
}
