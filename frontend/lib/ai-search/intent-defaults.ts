import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, IntentResolution } from "@/types/ai-search";
import type { Horizon } from "@/types/events";

const EMPTY_INTENT: AiSearchIntent = {
  intent: "search", asset: null, dateFrom: null, dateTo: null, category: null,
  topic: null, actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
  amount: null, entity: null, assetRole: "primary", sourceClass: null, sentiment: null,
  reactionSign: null, importance: null, horizon: null,
  metric: "events", sort: "newest", groupBy: "none", comparison: null, limit: 10,
};

const ASSET_TERMS = [
  [/(?:\bETH\b|\bethereum\b|ефір(?:у|ом|а)?)/iu, "ETH"],
  [/(?:\bBTC\b|\bbitcoin\b|біткоїн(?:у|ом|а)?)/iu, "BTC"],
  [/(?:\bSOL\b|\bsolana\b|солан(?:а|и|у|ою)?)/iu, "SOL"],
] as const;
const ETF_TERM = /\bETFs?\b|exchange[- ]traded\s+funds?/iu;
const INFLOW_TERM = /\binflows?\b|\b(?:money|funds?|capital)\s+(?:enters?|flows?\s+into)\b|приплив\p{L}*|надходжен\p{L}*|кошти\s+надход\p{L}*/iu;
const OUTFLOW_TERM = /\boutflows?\b|\bwithdrawals?\b|\b(?:money|funds?|capital)\s+(?:leaves?|flows?\s+out)\b|відток\p{L}*|відплив\p{L}*|виведен\p{L}*|кошти\s+(?:виход|залиша)\p{L}*/iu;
const BUYING_TERM = /\b(?:buy|buys|buying|purchases?|purchasing)\b|купівл\p{L}*|покуп\p{L}*/iu;
const SELLING_TERM = /\b(?:sell|sells|selling|sales?)\b|продаж\p{L}*|розпродаж\p{L}*/iu;

export type DeterministicConstraintResolution =
  | { status: "ready"; constraints: Partial<AiSearchIntent> }
  | { status: "clarification" | "rejected"; message: string };

function durationHorizon(value: number, unit: string): Horizon | null {
  if (/^m(?:in(?:ute)?s?)?$/iu.test(unit)) {
    return ({ 1: "1m", 5: "5m", 15: "15m" } as Record<number, Horizon>)[value] ?? null;
  }
  if (/^h(?:ours?)?$/iu.test(unit)) {
    return ({ 1: "1h", 4: "4h", 24: "24h" } as Record<number, Horizon>)[value] ?? null;
  }
  if (/^days?$/iu.test(unit)) return value === 1 ? "24h" : null;
  if (/^хвилин/iu.test(unit)) return ({ 1: "1m", 5: "5m", 15: "15m" } as Record<number, Horizon>)[value] ?? null;
  if (/^годин/iu.test(unit)) return ({ 1: "1h", 4: "4h", 24: "24h" } as Record<number, Horizon>)[value] ?? null;
  if (/^д(?:ень|ні|нів)$/iu.test(unit)) return value === 1 ? "24h" : null;
  return null;
}

function explicitHorizons(question: string): { values: Horizon[]; unsupported: boolean } {
  const values = new Set<Horizon>();
  let unsupported = false;
  const add = (rawValue: string, unit: string) => {
    const horizon = durationHorizon(Number(rawValue), unit);
    if (horizon) values.add(horizon);
    else unsupported = true;
  };
  for (const match of question.matchAll(/\b(\d+)\s*(m|h)\b/giu)) add(match[1], match[2]);
  for (const match of question.matchAll(/\bafter\s+(\d+)\s+(minutes?|hours?|days?)\b/giu)) add(match[1], match[2]);
  for (const match of question.matchAll(/\b(\d+)\s+(minutes?|hours?|days?)\s+later\b/giu)) add(match[1], match[2]);
  for (const match of question.matchAll(/\b(\d+)\s+(minutes?|hours?|days?)\s+after\b/giu)) add(match[1], match[2]);
  for (const match of question.matchAll(/через\s+(\d+)\s+(хвилин\p{L}*|годин\p{L}*|д(?:ень|ні|нів))/giu)) add(match[1], match[2]);
  if (/через\s+добу/iu.test(question)) values.add("24h");
  return { values: [...values], unsupported };
}

export function resolveDeterministicConstraints(question: string): DeterministicConstraintResolution {
  const assets = ASSET_TERMS.filter(([pattern]) => pattern.test(question)).map(([, asset]) => asset);
  if (new Set(assets).size > 1) {
    return { status: "clarification", message: "Choose one asset: BTC, ETH or SOL." };
  }
  const horizons = explicitHorizons(question);
  if (horizons.unsupported) {
    return { status: "clarification", message: "Use one supported horizon: 1m, 5m, 15m, 1h, 4h or 24h." };
  }
  if (horizons.values.length > 1) {
    return { status: "clarification", message: "Choose one Reaction V2 horizon." };
  }
  if (INFLOW_TERM.test(question) && OUTFLOW_TERM.test(question)) {
    return { status: "clarification", message: "Please choose either inflows or outflows." };
  }
  if (BUYING_TERM.test(question) && SELLING_TERM.test(question)) {
    return { status: "clarification", message: "Please choose either buying or selling." };
  }
  return { status: "ready", constraints: explicitFacts(question) };
}

function explicitFacts(question: string): Partial<AiSearchIntent> {
  const facts: Partial<AiSearchIntent> = {};
  const assets = ASSET_TERMS.filter(([pattern]) => pattern.test(question)).map(([, asset]) => asset);
  if (new Set(assets).size === 1) facts.asset = assets[0];

  const horizons = explicitHorizons(question).values;
  if (horizons.length === 1) facts.horizon = horizons[0];
  const dates = [...question.matchAll(/\b(20\d{2}-\d{2}-\d{2})\b/g)].map((match) => match[1]);
  const year = dates.length === 0 ? question.match(/\b(20\d{2})\b/)?.[1] : undefined;
  if (dates.length >= 2) {
    facts.dateFrom = dates[0];
    facts.dateTo = dates[1];
  } else if (dates.length === 1) {
    facts.dateFrom = dates[0];
    facts.dateTo = dates[0];
  } else if (year) {
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
  const etfApproval = /\b(?:approve|approves|approved|approval|approvals|greenlight(?:s|ed)?)\b|схвал\p{L}*|затверд\p{L}*/iu.test(question);
  const etfRejection = /\b(?:reject|rejects|rejected|rejection|denies|denied)\b|відхил\p{L}*/iu.test(question);
  const etfDelay = /\b(?:delay|delays|delayed|postpone|postpones|postponed|defer|defers|deferred)\b|відклад\p{L}*|перенес\p{L}*/iu.test(question);
  if (ETF_TERM.test(question) && INFLOW_TERM.test(question)) {
    Object.assign(facts, { topic: "etf_inflow", actorType: "ETF", action: "deposit", direction: "inflow", assetRole: "primary" });
    facts.category = null;
  } else if (ETF_TERM.test(question) && OUTFLOW_TERM.test(question)) {
    Object.assign(facts, { topic: "etf_outflow", actorType: "ETF", action: "withdraw", direction: "outflow", assetRole: "primary" });
    facts.category = null;
  } else if (ETF_TERM.test(question) && etfApproval) {
    Object.assign(facts, { topic: "etf_approval", actorType: "unknown", action: "approve", direction: "neutral", assetRole: "primary" });
    facts.category = null;
  } else if (ETF_TERM.test(question) && etfRejection) {
    Object.assign(facts, { topic: "etf_rejection", actorType: "unknown", action: "reject", direction: "neutral", assetRole: "primary" });
    facts.category = null;
  } else if (ETF_TERM.test(question) && etfDelay) {
    Object.assign(facts, { topic: "etf_delay", actorType: "unknown", action: null, direction: "neutral", assetRole: "primary" });
    facts.category = null;
  } else if (ETF_TERM.test(question)) {
    facts.topic = "etf";
    facts.category = null;
  }
  if (/\bhack(?:ed|s|ing)?\b|\bexploit(?:ed|s|ing)?\b|\bsecurity\s+breach(?:es)?\b|злам|експлойт|кібератак/iu.test(question)) {
    Object.assign(facts, { topic: "hack", action: null, direction: "unknown" });
    if (/\b(?:exchange|exchanges)\b|бірж/iu.test(question)) facts.actorType = "exchange";
    else if (/\b(?:protocol|protocols|bridge|bridges)\b|протокол|мост/iu.test(question)) facts.actorType = "protocol";
    facts.category = null;
  }
  if (/\bCPI\b|consumer\s+price\s+index|індекс\s+споживчих\s+цін|інфляц/iu.test(question)) {
    Object.assign(facts, { topic: "cpi", action: null, direction: "unknown" });
    facts.category = null;
  } else if (/\b(?:rate|interest\s+rate)s?\b[^.]{0,35}\b(?:hike|hikes|hiked|increase|increases|increased|raise|raises|raised|tightening)\b|\b(?:hike|hikes|hiked|increase|increases|increased|raise|raises|raised|tightening)\b[^.]{0,35}\b(?:rate|interest\s+rates?)\b|підвищен\p{L}*\s+(?:процентн\p{L}*|відсотков\p{L}*)?\s*став|монетарн\p{L}*\s+посиленн/iu.test(question)) {
    Object.assign(facts, { topic: "fed_rate_hike", action: null, direction: "unknown", actorType: "unknown" });
    facts.category = null;
  } else if (/\b(?:rate|interest\s+rate)s?\b[^.]{0,35}\b(?:cut|cuts|lower|lowers|lowered|decrease|decreases|decreased|easing)\b|\b(?:cut|cuts|lower|lowers|lowered|decrease|decreases|decreased|easing)\b[^.]{0,35}\b(?:rates?|interest\s+rates?)\b|знижен\p{L}*\s+(?:процентн\p{L}*|відсотков\p{L}*)?\s*став|монетарн\p{L}*\s+пом.?якшенн/iu.test(question)) {
    Object.assign(facts, { topic: "fed_rate_cut", action: null, direction: "unknown", actorType: "unknown" });
    facts.category = null;
  } else if (/\b(?:Fed|FOMC)\b|Federal\s+Reserve|Федеральн\p{L}*\s+резерв/iu.test(question)) {
    Object.assign(facts, { topic: "fed", action: null, direction: "unknown" });
    facts.category = null;
  } else if (/\bmacro(?:economic)?\b|макро/iu.test(question)) {
    facts.topic = "macro";
    facts.category = null;
  }
  if (/\blisting\b|лістинг/iu.test(question)) {
    facts.topic = "listing";
    facts.category = null;
  }
  if (/\b(?:lawsuits?|litigation|sue|sues|sued)\b|позов/iu.test(question)) {
    facts.topic = "lawsuit";
    facts.category = null;
  }
  if (!ETF_TERM.test(question) && /\b(?:regulatory|regulator|regulators|SEC|CFTC)\b[^.]{0,60}\b(?:approve|approves|approved|approval|approvals|authorization)\b|\b(?:approve|approves|approved|approval|approvals|authorization)\b[^.]{0,60}\b(?:regulatory|regulator|regulators|SEC|CFTC)\b|регулятор\p{L}*[^.]{0,60}(?:схвал|затверд)/iu.test(question)) {
    Object.assign(facts, { topic: "regulatory_approval", actorType: "unknown", action: "approve", direction: "neutral" });
    facts.category = null;
  } else if (/\b(?:regulatory|regulator|regulators|SEC|CFTC)\b[^.]{0,60}\b(?:enforcement|crackdown|charges?|fines?|penalties|sanctions?)\b|\b(?:enforcement|crackdown|charges?|fines?|penalties|sanctions?)\b[^.]{0,60}\b(?:regulatory|regulator|regulators|SEC|CFTC)\b|регулятор\p{L}*[^.]{0,60}(?:тиск|переслідуван|санкц|штраф)/iu.test(question)) {
    Object.assign(facts, { topic: "regulatory_enforcement", actorType: "unknown", action: null, direction: "neutral" });
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
  if (facts.topic === "etf_inflow" || facts.topic === "etf_outflow") {
    // Direction-specific ETF constraints always outrank generic topic wording.
  } else if (/large\s+(?:financial\s+)?investments?|велик\S*\s+(?:фінансов\S*\s+)?інвестиці|больш\S*\s+инвестиц/iu.test(question)) {
    facts.topic = "large_investment";
    facts.action = "invest";
    facts.direction = "inflow";
    facts.magnitude = "large";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/(?:large\s+)?institutional\s+(?:purchase|purchases|buy|buying)|\bwhales?\b[^.]{0,45}\b(?:buy|buys|buying|purchase|purchases|accumulate|accumulates|accumulation)\b|\b(?:buy|buys|buying|purchase|purchases|accumulation)\b[^.]{0,45}\bwhales?\b|(?:велик\S*\s+)?інституційн\S*\s+(?:купівл|придбан|покуп)|кит\p{L}*[^.]{0,45}(?:куп|накопич)|(?:купівл|покуп|накопич)\p{L}*[^.]{0,45}кит\p{L}*/iu.test(question)) {
    facts.topic = "institutional_purchase";
    facts.actorType = /\bwhales?\b|кит/iu.test(question) ? "whale" : "institution";
    facts.action = "buy";
    facts.direction = "inflow";
    facts.magnitude = /\blarge\b|велик/iu.test(question) ? "large" : "unknown";
    facts.assetRole = "primary";
    facts.category = null;
  } else if (/institutional\s+(?:sell|selling|sales)|sales?\s+by\s+(?:large\s+)?investors?|(?:large\s+)?investors?\s+(?:sell|selling|sales)|(?:продаж|розпродаж)\S*\s+(?:великими\s+)?інвестор|інституційн\S*\s+(?:продаж|розпродаж)|продаж\S*\s+крупн\S*\s+инвестор/iu.test(question)) {
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
  if (facts.action === undefined && BUYING_TERM.test(question)) {
    facts.action = "buy";
    facts.direction = "inflow";
  } else if (facts.action === undefined && SELLING_TERM.test(question)) {
    facts.action = "sell";
    facts.direction = "outflow";
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
  const resolution = resolveDeterministicConstraints(question);
  if (resolution.status !== "ready") return resolution;
  return humanClarification(resolution.constraints);
}

export function applyExplicitQuestionDefaults(
  question: string,
  resolution: IntentResolution,
  suppliedConstraints?: Partial<AiSearchIntent>,
): IntentResolution {
  const constraintResolution = suppliedConstraints
    ? { status: "ready" as const, constraints: suppliedConstraints }
    : resolveDeterministicConstraints(question);
  if (constraintResolution.status !== "ready") return constraintResolution;
  const facts = constraintResolution.constraints;
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
export function resolveExplicitQuestion(
  question: string,
  suppliedConstraints?: Partial<AiSearchIntent>,
): IntentResolution | null {
  const constraintResolution = suppliedConstraints
    ? { status: "ready" as const, constraints: suppliedConstraints }
    : resolveDeterministicConstraints(question);
  if (constraintResolution.status !== "ready") return constraintResolution;
  const facts = constraintResolution.constraints;
  if (facts.intent !== "aggregate" || !facts.asset || !facts.topic) return null;
  try {
    return { status: "ready", intent: validateIntent({ ...EMPTY_INTENT, ...facts }) };
  } catch {
    return null;
  }
}
