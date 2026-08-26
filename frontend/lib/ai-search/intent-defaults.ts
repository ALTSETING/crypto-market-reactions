import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, IntentResolution } from "@/types/ai-search";

const EMPTY_INTENT: AiSearchIntent = {
  intent: "search", asset: null, dateFrom: null, dateTo: null, category: null,
  topic: null, actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
  amount: null, entity: null, assetRole: "primary", sourceClass: null, sentiment: null,
  reactionSign: null, importance: null, horizon: null,
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
  const amountMatch = question.match(/(?:\$|USD\s*|US\$\s*|€|EUR\s*)(\d+(?:[.,]\d+)?)\s*(billion|million|bn|bil|mm|m|b)\b/iu);
  if (amountMatch) {
    const numeric = Number(amountMatch[1].replace(",", "."));
    const multiplier = /^(?:b|bn|bil|billion)$/iu.test(amountMatch[2]) ? 1_000_000_000 : 1_000_000;
    if (Number.isFinite(numeric) && numeric > 0) facts.amount = {
      currency: /€|EUR/iu.test(amountMatch[0]) ? "EUR" : "USD",
      value: numeric * multiplier,
    };
  }
  if (/\bSEC\s+filings?\b|\b(?:8-K|10-K|10-Q|S-1|19b-4)\b|реєстраційн\S*\s+заяв/iu.test(question)) {
    facts.topic = "sec_filings";
    facts.category = null;
  } else if (/\bSEC\b|Securities\s+and\s+Exchange\s+Commission|рішення\s+SEC/iu.test(question)) {
    facts.topic = "sec";
    facts.category = null;
  }
  if (/\bETF\b|exchange[- ]traded\s+fund/iu.test(question)) {
    facts.topic = "etf";
    facts.category = null;
  }
  if (/\bhack(?:ed|s)?\b|\bexploit(?:ed|s)?\b|злам/iu.test(question)) {
    facts.topic = "hack";
    facts.category = null;
  }
  if (/\bCPI\b|consumer\s+price\s+index/iu.test(question)) {
    facts.topic = "cpi";
    facts.category = null;
  } else if (/\b(?:Fed|FOMC)\b|Federal\s+Reserve/iu.test(question)) {
    facts.topic = "fed";
    facts.category = null;
  } else if (/\bmacro(?:economic)?\b|макро/iu.test(question)) {
    facts.topic = "macro";
    facts.category = null;
  }
  if (/\blisting\b|лістинг/iu.test(question)) {
    facts.topic = "listing";
    facts.category = null;
  }
  if (/\blawsuit\b|\blitigation\b|позов/iu.test(question)) {
    facts.topic = "lawsuit";
    facts.category = null;
  }
  if (/\bupgrade\b|оновлен/iu.test(question)) {
    facts.topic = "upgrade";
    facts.category = null;
  }
  if (/\bstaking\b|стейкінг/iu.test(question)) {
    facts.topic = "staking";
    facts.category = null;
  }
  if (/large\s+(?:financial\s+)?investments?|велик\S*\s+(?:фінансов\S*\s+)?інвестиці|больш\S*\s+инвестиц/iu.test(question)) {
    facts.topic = "large_investment";
    facts.action = "invest";
    facts.direction = "inflow";
    facts.magnitude = "large";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/(?:large\s+)?institutional\s+(?:purchase|purchases|buy|buying)|(?:велик\S*\s+)?інституційн\S*\s+(?:купівл|придбан|покуп)/iu.test(question)) {
    facts.topic = "institutional_purchase";
    facts.actorType = "institution";
    facts.action = "buy";
    facts.direction = "inflow";
    facts.magnitude = /\blarge\b|велик/iu.test(question) ? "large" : "unknown";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/institutional\s+(?:sell|selling|sales)|продаж\S*\s+(?:великими\s+)?інвестор|інституційн\S*\s+продаж|продаж\S*\s+крупн\S*\s+инвестор/iu.test(question)) {
    facts.topic = "institutional_selling";
    facts.actorType = /інвестор|investor/iu.test(question) ? "investor" : "institution";
    facts.action = "sell";
    facts.direction = "outflow";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/\b(?:capital\s+outflows?|outflows?\s+(?:of\s+)?capital)\b|відплив\S*\s+капітал|відтік\S*\s+капітал|отток\S*\s+капитал/iu.test(question)) {
    facts.topic = "capital_outflow";
    facts.action = "withdraw";
    facts.direction = "outflow";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/\b(?:capital\s+inflows?|inflows?\s+(?:of\s+)?capital)\b|приплив\S*\s+капітал|притік\S*\s+капітал|приток\S*\s+капитал/iu.test(question)) {
    facts.topic = "capital_inflow";
    facts.action = "deposit";
    facts.direction = "inflow";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/\bETF\s+inflows?\b/iu.test(question)) {
    facts.topic = "etf_inflow";
    facts.actorType = "ETF";
    facts.action = "deposit";
    facts.direction = "inflow";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/\bETF\s+outflows?\b/iu.test(question)) {
    facts.topic = "etf_outflow";
    facts.actorType = "ETF";
    facts.action = "withdraw";
    facts.direction = "outflow";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/\bfund(?:ing|raise|raising)\b|фінансуван|раунд\S*\s+фінанс/iu.test(question)) {
    facts.topic = "funding";
    facts.actorType = "unknown";
    facts.action = /rais|round|раунд/iu.test(question) ? "raise" : "fund";
    facts.direction = "inflow";
    facts.assetRole = "any";
    facts.category = null;
  } else if (/\bacquisitions?\b|\bacquires?\b|поглинан|придбанн\S*\s+компан/iu.test(question)) {
    facts.topic = "acquisition";
    facts.actorType = "unknown";
    facts.action = "acquire";
    facts.direction = "neutral";
    facts.assetRole = "any";
    facts.category = null;
  } else if (/large\s+purchases?|велик\S*\s+(?:купівл|покуп)/iu.test(question)) {
    facts.topic = "large_investment";
    facts.action = "buy";
    facts.direction = "inflow";
    facts.magnitude = "large";
    facts.assetRole = "primary";
    facts.category = null;
  }
  if (/\bnews media\b/i.test(question)) facts.sourceClass = "news_media";
  if (/\bpositive\s+sentiment\b|позитивн\S*\s+сентимент/iu.test(question)) {
    facts.sentiment = "positive";
    facts.reactionSign = null;
  } else if (/\bpositive(?:\s+\w+){0,2}\s+(?:market\s+)?(?:reactions?|events?)\b|позитивн\S*(?:\s+\S+){0,2}\s+(?:реакці|поді)/iu.test(question)) {
    facts.sentiment = null;
    facts.reactionSign = "positive";
    facts.horizon = facts.horizon ?? "24h";
  }
  if (/\bnegative\s+sentiment\b|негативн\S*\s+сентимент/iu.test(question)) {
    facts.sentiment = "negative";
    facts.reactionSign = null;
  } else if (/\bnegative(?:\s+\w+){0,2}\s+(?:market\s+)?(?:reactions?|events?)\b|негативн\S*(?:\s+\S+){0,2}\s+(?:реакці|поді)/iu.test(question)) {
    facts.sentiment = null;
    facts.reactionSign = "negative";
    facts.horizon = facts.horizon ?? "24h";
  }

  const limit = question.match(/\b(\d{1,2})\s+(?:biggest|largest|top)\b/i)?.[1];
  if (limit) facts.limit = Math.min(50, Number(limit));
  if (/\bcompare\b|порівн/iu.test(question)) {
    const hasPrimary = /primary documents?|первинн\S*\s+документ/iu.test(question);
    const hasNews = /news media|новинн\S*\s+медіа/iu.test(question);
    Object.assign(facts, {
      intent: "compare", metric: /median|медіан/iu.test(question) ? "median" : "mean",
      groupBy: "source_class",
      comparison: hasPrimary && hasNews ? { field: "sourceClass", left: "primary_document", right: "news_media" } : null,
    });
  } else if (/\b(?:how many|count|number of)\b|\bскільки\b/iu.test(question)) {
    Object.assign(facts, { intent: "count", metric: "count", sort: "newest" });
  } else if (/\b(?:biggest|largest)(?:\s+\w+){0,2}\s+(?:drops|losses|falls)\b|найбільш\S*\s+падін/iu.test(question)) {
    Object.assign(facts, { intent: "rank", metric: "reaction", sort: "losers", horizon: facts.horizon ?? "24h" });
  } else if (/\b(?:biggest|largest)(?:\s+\w+){0,2}\s+(?:gains|rises)\b|найбільш\S*\s+зростан/iu.test(question)) {
    Object.assign(facts, { intent: "rank", metric: "reaction", sort: "gainers", horizon: facts.horizon ?? "24h" });
  } else if (/\bmedian\b|медіан/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "median", horizon: facts.horizon ?? null });
  } else if (/\baverage\b|\bmean\b|середн/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "mean", horizon: facts.horizon ?? null });
  } else if (/\breact(?:ed|ion)?\b|реаг/iu.test(question)) {
    Object.assign(facts, { intent: "aggregate", metric: "mean", horizon: facts.horizon ?? null });
  }
  return facts;
}

function humanClarification(intent: Partial<AiSearchIntent>): IntentResolution | null {
  if (["aggregate", "rank", "compare"].includes(intent.intent ?? "") && !intent.asset) {
    return { status: "clarification", message: "Which asset should I analyze: BTC, ETH or SOL?" };
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

/** Returns a ready intent only when deterministic parsing found a complete bounded analytics question. */
export function resolveExplicitQuestion(question: string): IntentResolution | null {
  const facts = explicitFacts(question);
  if (facts.intent !== "aggregate" || !facts.asset || !facts.topic) return null;
  try {
    return { status: "ready", intent: validateIntent({ ...EMPTY_INTENT, ...facts }) };
  } catch {
    return null;
  }
}
