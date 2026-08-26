import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, IntentResolution } from "@/types/ai-search";
import type { EventCategory, Horizon, SourceType } from "@/types/events";

const sourceTerms: Array<[RegExp, SourceType]> = [
  [/primary documents?|primary_document|первинн(?:і|их) документ/i, "primary_document"],
  [/news media|news_media|новинн(?:і|их) медіа/i, "news_media"],
  [/official announcements?|official_announcement|офіційн(?:і|их) оголошенн/i, "official_announcement"],
];
const categoryTerms: Array<[RegExp, EventCategory]> = [
  [/SEC filings?|регуляторн/i, "regulation"],
  [/\bETF\b/i, "etf"],
  [/hack|злам/i, "hack"],
  [/staking|стейкінг/i, "staking"],
  [/network outage|зб(?:і|о)й мереж/i, "network_activity"],
  [/protocol upgrade/i, "protocol_upgrade"],
];

function occurrences<T>(question: string, entries: Array<[RegExp, T]>): T[] {
  return entries.filter(([pattern]) => pattern.test(question)).map(([, value]) => value);
}

function yearRange(question: string): [string | null, string | null] {
  const dates = [...question.matchAll(/\b(20\d{2}-\d{2}-\d{2})\b/g)].map((match) => match[1]);
  if (dates.length >= 2) return [dates[0], dates[1]];
  if (dates.length === 1) return [dates[0], dates[0]];
  const years = [...question.matchAll(/\b(20\d{2})\b/g)].map((match) => Number(match[1]));
  if (years.length === 0) return [null, null];
  const first = Math.min(...years);
  const last = Math.max(...years);
  return [`${first}-01-01`, `${last}-12-31`];
}

function horizonFrom(question: string): Horizon | null {
  const match = question.match(/(?:через|after|at)?\s*(24h|4h|1h|15m|5m|1m)\b/i);
  return (match?.[1]?.toLowerCase() as Horizon | undefined) ?? null;
}

function baseIntent(question: string): AiSearchIntent {
  const assets = [...question.matchAll(/\b(BTC|ETH|SOL)\b/gi)].map((match) => match[1].toUpperCase());
  const uniqueAssets = [...new Set(assets)];
  const sources = occurrences(question, sourceTerms);
  const categories = occurrences(question, categoryTerms);
  const [dateFrom, dateTo] = yearRange(question);
  const limitMatch = question.match(/\b(\d{1,3})\b\s*(?:biggest|largest|top|найбільш|поді|events?)/i)
    ?? question.match(/(?:show|покажи|top)\s+(\d{1,3})\b/i);
  const limit = limitMatch ? Number(limitMatch[1]) : 10;
  const isCompare = /compare|порівняй/i.test(question);
  const isRank = /top|biggest|largest|найбільш/i.test(question) && /gain|rise|зростан|loss|drop|fall|падін/i.test(question);
  const isMean = /average|mean|середн|how did[\s\S]{0,40}react|як[\s\S]{0,40}реагув/i.test(question);
  const isMedian = /median|медіан/i.test(question);
  const isShare = /share|percentage|частк|відсот/i.test(question) && /positive|negative|позитив|негатив/i.test(question);
  const isCount = /how many|count|скільки/i.test(question);
  const sourceClass = sources.length === 1 && !isCompare ? sources[0] : null;
  const sentiment = /positive|позитив/i.test(question) ? "positive" : /negative|негатив/i.test(question) ? "negative" : /neutral|нейтрал/i.test(question) ? "neutral" : null;
  const importance = /high importance|важлив(?:і|их)/i.test(question) ? "high" : /low importance/i.test(question) ? "low" : /medium importance/i.test(question) ? "medium" : null;

  return {
    intent: isCompare ? "compare" : isRank ? "rank" : (isMean || isMedian || isShare) ? "aggregate" : isCount ? "count" : "search",
    asset: uniqueAssets.length === 1 ? uniqueAssets[0] as AiSearchIntent["asset"] : null,
    dateFrom,
    dateTo,
    category: categories.length === 1 ? categories[0] : null,
    topic: null,
    actorType: "unknown",
    action: null,
    direction: "unknown",
    magnitude: "unknown",
    amount: null,
    entity: null,
    assetRole: "primary",
    sourceClass,
    sentiment,
    reactionSign: null,
    importance,
    horizon: horizonFrom(question),
    metric: isMean ? "mean" : isMedian ? "median" : isShare ? "sign_share" : isRank ? "reaction" : isCount ? "count" : "events",
    sort: /loss|drop|fall|падін/i.test(question) ? "losers" : isRank ? "gainers" : /oldest|найстар/i.test(question) ? "oldest" : "newest",
    groupBy: isCompare ? "source_class" : "none",
    comparison: isCompare && sources.length === 2 ? { field: "sourceClass", left: sources[0], right: sources[1] } : null,
    limit,
  };
}

export function parseMockIntent(question: string): IntentResolution {
  const assetMentions = new Set([...question.matchAll(/\b(BTC|ETH|SOL)\b/gi)].map((match) => match[1].toUpperCase()));
  if (assetMentions.size > 1) return { status: "clarification", message: "Choose one asset for this MVP query." };
  const candidate = baseIntent(question);
  if (/\btop\b|найбільш/i.test(question) && candidate.intent !== "rank") {
    return { status: "clarification", message: "Specify whether to rank gainers or losers and choose a Reaction V2 horizon." };
  }
  const needsReaction = ["aggregate", "rank", "compare"].includes(candidate.intent);
  if (needsReaction && !candidate.asset) return { status: "clarification", message: "Which asset should be analyzed: BTC, ETH, or SOL?" };
  if (needsReaction && !candidate.horizon) return { status: "clarification", message: "Choose one Reaction V2 horizon: 1m, 5m, 15m, 1h, 4h, or 24h." };
  if (candidate.intent === "compare" && !candidate.comparison) return { status: "clarification", message: "Specify two source classes to compare." };
  if (/reaction|реагув/i.test(question) && candidate.intent === "search") return { status: "clarification", message: "Specify a metric and one Reaction V2 horizon." };
  try {
    return { status: "ready", intent: validateIntent(candidate) };
  } catch (error) {
    return { status: "clarification", message: error instanceof Error ? error.message : "Please make the question more specific." };
  }
}
