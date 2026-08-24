import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, IntentResolution } from "@/types/ai-search";

const EMPTY_INTENT: AiSearchIntent = {
  intent: "search", asset: null, dateFrom: null, dateTo: null, category: null,
  sourceClass: null, sentiment: null, importance: null, horizon: null,
  metric: "events", sort: "newest", groupBy: "none", comparison: null, limit: 10,
};

function explicitFacts(question: string): Partial<AiSearchIntent> {
  const facts: Partial<AiSearchIntent> = {};
  const assetMatches = [
    [/(?:\bETH\b|\bethereum\b|ефір(?:у|ом|а)?)/iu, "ETH"],
    [/(?:\bBTC\b|\bbitcoin\b|біткоїн(?:у|ом|а)?)/iu, "BTC"],
    [/(?:\bSOL\b|\bsolana\b|солан(?:а|и|у|ою)?)/iu, "SOL"],
  ] as const;
  const assets = assetMatches.filter(([pattern]) => pattern.test(question)).map(([, asset]) => asset);
  if (new Set(assets).size === 1) facts.asset = assets[0];

  const horizon = question.match(/\b(24h|4h|1h|15m|5m|1m)\b/i)?.[1]?.toLowerCase();
  if (horizon) facts.horizon = horizon as AiSearchIntent["horizon"];
  const year = question.match(/\b(20\d{2})\b/)?.[1];
  if (year) {
    facts.dateFrom = `${year}-01-01`;
    facts.dateTo = `${year}-12-31`;
  }
  if (/\bSEC\s+filings?\b/i.test(question)) facts.category = "regulation";
  if (/\bETF\b/i.test(question)) facts.category = "etf";
  if (/\bnews media\b/i.test(question)) facts.sourceClass = "news_media";
  if (/\bpositive\b|позитивн/iu.test(question)) facts.sentiment = "positive";
  if (/\bnegative\b|негативн/iu.test(question)) facts.sentiment = "negative";

  const limit = question.match(/\b(\d{1,2})\s+(?:biggest|largest|top)\b/i)?.[1];
  if (limit) facts.limit = Math.min(50, Number(limit));
  if (/\b(?:how many|count|number of)\b|\bскільки\b/iu.test(question)) {
    Object.assign(facts, { intent: "count", metric: "count", sort: "newest" });
  } else if (/\b(?:biggest|largest)(?:\s+\w+){0,2}\s+(?:drops|losses|falls)\b|найбільш\S*\s+падін/iu.test(question)) {
    Object.assign(facts, { intent: "rank", metric: "reaction", sort: "losers" });
  } else if (/\b(?:biggest|largest)(?:\s+\w+){0,2}\s+(?:gains|rises)\b|найбільш\S*\s+зростан/iu.test(question)) {
    Object.assign(facts, { intent: "rank", metric: "reaction", sort: "gainers" });
  } else if (/\bmedian\b|медіан/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "median" });
  } else if (/\baverage\b|\bmean\b|середн/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "mean" });
  } else if (/\breact(?:ed|ion)?\b|реагув/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "mean" });
  }
  return facts;
}

function humanClarification(intent: Partial<AiSearchIntent>): IntentResolution | null {
  if (["aggregate", "rank", "compare"].includes(intent.intent ?? "") && !intent.asset) {
    return { status: "clarification", message: "Which asset should I analyze: BTC, ETH or SOL?" };
  }
  if (["aggregate", "rank", "compare"].includes(intent.intent ?? "") && !intent.horizon) {
    return { status: "clarification", message: "Which reaction horizon should I use: 1h, 4h or 24h?" };
  }
  return null;
}

export function explicitQuestionClarification(question: string): IntentResolution | null {
  return humanClarification(explicitFacts(question));
}

export function applyExplicitQuestionDefaults(question: string, resolution: IntentResolution): IntentResolution {
  const facts = explicitFacts(question);
  const source = resolution.status === "ready" ? resolution.intent : EMPTY_INTENT;
  const candidate = { ...source, ...facts };
  const clarification = humanClarification(candidate);
  if (clarification) return clarification;
  if (resolution.status !== "ready" && !["count", "aggregate", "rank"].includes(candidate.intent)) return resolution;
  try {
    return { status: "ready", intent: validateIntent(candidate) };
  } catch {
    return resolution.status === "clarification"
      ? { status: "clarification", message: "Could you make the historical analysis request a little more specific?" }
      : resolution;
  }
}
