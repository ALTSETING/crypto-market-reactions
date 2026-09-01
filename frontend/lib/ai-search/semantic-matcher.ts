import type {
  AiAction,
  AiActorType,
  AiAssetRole,
  AiDirection,
  AiMagnitude,
  AiSearchIntent,
  AiTopic,
  AnalyticsEvent,
} from "@/types/ai-search";
import type { Asset } from "@/types/events";

export const SEMANTIC_CONFIDENCE_THRESHOLD = 0.6 as const;
export const LARGE_INVESTMENT_USD_THRESHOLD = 50_000_000 as const;
export const FIXED_EUR_USD_RATE = 1.08 as const;

export interface SemanticAmount {
  currency: "USD" | "EUR";
  value: number;
  normalizedUsd: number | null;
  source: string;
}

export interface SemanticEventInput extends Pick<AnalyticsEvent, "title" | "assets" | "category"> {
  primaryAsset?: Asset | null;
}

export interface SemanticEventMatch {
  matched: boolean;
  confidence: number;
  relevanceScore: number;
  reasons: string[];
  assetRole: Exclude<AiAssetRole, "any"> | "unknown";
  amount: SemanticAmount | null;
  magnitude: AiMagnitude;
  actorType: AiActorType;
  action: AiAction | null;
  direction: AiDirection;
}

const ASSET_PATTERNS: Record<Asset, RegExp> = {
  BTC: /\b(?:BTC|Bitcoin)\b|біткоїн|биткоин/iu,
  ETH: /\b(?:ETH|Ether|Ethereum)\b|ефір|эфир/iu,
  SOL: /\b(?:SOL|Solana)\b|солан/iu,
};

const ACTION_PATTERNS: ReadonlyArray<readonly [AiAction, RegExp]> = [
  ["liquidate", /\bliquidat(?:e|es|ed|ion|ions)\b|ліквідац|ликвидац/iu],
  ["divest", /\bdivest(?:s|ed|ment|ments)?\b|\bexits?\b[^.]{0,45}\b(?:investment|stake|position)\b|\b(?:cuts?|reduces?)\b[^.]{0,35}\bstake\b/iu],
  ["sell", /\b(?:sell|sells|selling|sold|sale|sales|redemption|redemptions|offload|offloads|offloaded|dump|dumps|dumped|exits? (?:its )?position)\b|продаж|продав|викуп.*паїв/iu],
  ["withdraw", /\b(?:withdraw|withdraws|withdrew|withdrawal|withdrawals|outflow|outflows)\b|\bETFs?\s+(?:lose|loses|lost|shed|sheds)\b|виведен|відплив|відтік|отток/iu],
  ["unstake", /\bunstak(?:e|es|ed|ing)\b/iu],
  ["delist", /\bdelist(?:s|ed|ing)?\b/iu],
  ["reject", /\b(?:reject|rejects|rejected|denies|denied)\b|відхил|отклони/iu],
  ["exploit", /\bexploit(?:s|ed|ing)?\b/iu],
  ["hack", /\b(?:hack|hacks|hacked|hacking|security breach|data breach)\b|злам|взлом/iu],
  ["acquire", /\b(?:acquire|acquires|acquired|acquisition|acquisitions|takeover|takeovers)\b|поглинан|придба.*компан/iu],
  ["raise", /\b(?:raise|raises|raised|raising|fundraise|fundraises|fundraised|fundraising)\b|раунд.*фінанс|залучил.*капітал/iu],
  ["fund", /\b(?:funded|funding|finances?|financed)\b|фінансуван/iu],
  ["invest", /\b(?:invest|invests|invested|investing|investment|investments)\b|інвестиц|інвестув|инвестиц/iu],
  ["buy", /\b(?:buy|buys|buying|bought|purchase|purchases|purchased|accumulates?|accumulated|adds?|added)\b|купівл|купил|придбав|придбан/iu],
  ["deposit", /\b(?:deposit|deposits|deposited|inflow|inflows)\b|приплив|притік|приток/iu],
  ["approve", /\b(?:approve|approves|approved|approval|approvals)\b|схвал|одобр/iu],
  ["file", /\b(?:file|files|filed|filing|filings)\b/iu],
  ["sue", /\b(?:sue|sues|sued|lawsuit|lawsuits|litigation)\b|позов|иск/iu],
  ["list", /\b(?:list|lists|listed|listing|listings)\b/iu],
  ["upgrade", /\b(?:upgrade|upgrades|upgraded|hard fork)\b|оновлен|обновлен/iu],
  ["stake", /\bstak(?:e|es|ed|ing)\b|стейкінг|стейкинг/iu],
];

const STRONG_LARGE_PATTERN = /\b(?:massive investment|major purchase|billion[- ]dollar|large treasury purchase|major institutional investment)\b|масштабн\S*\s+інвестиц|велика\S*\s+казначейськ\S*\s+купівл/iu;
const INSTITUTION_PATTERN = /\b(?:institutions?|institutional|bank|asset manager|pension|endowment|university endowment|family office|treasury firm|treasury|BlackRock|Fidelity|Grayscale|MicroStrategy|Strategy)\b|інституц|банк|казначейств/iu;
const FUND_PATTERN = /(?:^|:\s)funds?\b|\b(?:hedge|investment|pension|crypto|capital|large cap|mutual|sovereign)\s+funds?\b|\bventure capital\b|\bVC\b|фонд/iu;
const ETF_PATTERN = /\b(?:ETF|ETFs|exchange[- ]traded funds?)\b/iu;
const COMPANY_PATTERN = /\b(?:company|companies|corporation|corp\.?|Inc\.?|Ltd\.?)\b|компан/iu;
const REGULATOR_PATTERN = /\b(?:SEC|CFTC|regulator|regulators|Securities and Exchange Commission)\b|регулятор/iu;
const EXCHANGE_PATTERN = /\b(?:exchange|Binance|Coinbase|Kraken|OKX)\b|бірж|бирж/iu;
const PROTOCOL_PATTERN = /\b(?:protocol|network|foundation|DAO|bridge)\b|протокол|мереж/iu;
const WHALE_PATTERN = /\bwhales?\b|кит(?:и|ів|ы|ов)?/iu;
const INVESTOR_PATTERN = /\b(?:investor|investors|holder|holders)\b|інвестор|инвестор/iu;

const CRYPTO_ASSET_SOURCE = String.raw`(?:BTC|Bitcoin|ETH|Ether|Ethereum|SOL|Solana)`;
const TRADE_ACTION_SOURCE = String.raw`(?:buy|buys|buying|bought|purchase|purchases|purchased|adds?|added|accumulates?|accumulated|sell|sells|selling|sold|sale|sales|offload|offloads|offloaded|dump|dumps|dumped|divests?|divested|withdraw|withdraws|withdrew|outflow|outflows|redemption|redemptions)`;
const NEGATED_TRADE_PATTERN = /\b(?:pause[sd]?|skip[sp]?|halt(?:s|ed)?|stop(?:s|ped)?)\b[^.]{0,45}\b(?:buy|buys|buying|purchase|purchases|purchasing)\b|\bmay\s+slow\b[^.]{0,40}\b(?:buy|buys|buying|purchase|purchases)\b|\b(?:reports?\s+)?no\s+sales?\b/iu;
const CRYPTO_TREASURY_EQUITY_PATTERN = /\b(?:Bitcoin|Ethereum|Ether|Solana|BTC|ETH|SOL)\s+(?:treasury\s+)?(?:shares?|stocks?)\b/iu;
const HACK_INCIDENT_PATTERN = /\b(?:hack|hacks|hacked|hacking|exploit|exploits|exploited|security breach|data breach)\b/iu;
const HACK_NON_INCIDENT_PATTERN = /\b(?:no|without|prevent|prevents|prevented|prevention|safe\s+against|avoids?|detects?|detection|den(?:y|ies|ied)|warns?\s+of\s+(?:a\s+)?potential|potential)\b[^.]{0,60}\b(?:hack|exploit|breach)|\b(?:hack|exploit|breach)\b[^.]{0,45}\b(?:prevented|avoided|detection)\b/iu;
const NON_CRYPTO_SELL_PATTERN = /\b(?:preferred\s+)?(?:stock|shares?|equity)\s+sales?\b|\bsales?\s+of\s+(?:preferred\s+)?(?:stock|shares?|equity)\b|\bexits?\b[^,.;:]{0,45}\b(?:stock|shares?|equity)\b/iu;

function round(value: number): number {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

export function extractSemanticAmount(text: string): SemanticAmount | null {
  const match = text.match(/(\$|USD\s*|US\$\s*|€|EUR\s*)(\d{1,3}(?:[,.]\d{3})*(?:[.,]\d+)?)\s*(billion|million|bn|bil|mm|m|b)\b/iu);
  if (!match) return null;
  const currency = /€|EUR/iu.test(match[1]) ? "EUR" : "USD";
  const raw = match[2].replace(/,(?=\d{3}(?:\D|$))/g, "").replace(",", ".");
  const numeric = Number(raw);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const unit = match[3].toLowerCase();
  const multiplier = /^(?:b|bn|bil|billion)$/u.test(unit) ? 1_000_000_000 : 1_000_000;
  const value = numeric * multiplier;
  return { currency, value, normalizedUsd: currency === "USD" ? value : round(value * FIXED_EUR_USD_RATE), source: match[0] };
}

function inferAction(text: string, targetAsset: Asset | null): AiAction | null {
  text = text.replace(/\b(?:end|ends|ended|ending)\b[^,.;:]{0,45}\b(?:inflow|outflow)\s+streak\b/giu, "");
  if (/\bacqui(?:re|res|red|ring)\b\s+(?:(?:more\s+than|another)\s+)?(?:\$?[\d,.]+\s*(?:million|billion|mn|bn|m|b)?\s+)?(?:in\s+)?(?:BTC|Bitcoin|ETH|Ether|Ethereum|SOL|Solana)\b|\bacqui(?:re|res|red|ring)\b[^.]{0,80}\bfor (?:its )?treasury\b/iu.test(text)) return "buy";
  if (NEGATED_TRADE_PATTERN.test(text)) return null;
  if (/\bbuys?\s+back\b|\b(?:gets?|calls?)\b[^,.;:]{0,50}\b(?:a\s+)?["'‘’]?buy["'‘’]?\b|\bbuy\s+ratings?\b|\bdid\s+you\s+buy\b/iu.test(text)) return null;
  const equityTrade = text.match(/\b(?:buy|buys|bought|purchase|purchases|purchased|invests?|invested)\b[^,;:]{0,80}\b(?:shares?|stocks?|stake\s+in|bank)\b/iu)?.[0];
  if (equityTrade && !/\bas\s+shares?\b/iu.test(equityTrade)) {
    const containsCryptoAsset = new RegExp(String.raw`\b${CRYPTO_ASSET_SOURCE}\b`, "iu").test(equityTrade);
    if (!containsCryptoAsset || CRYPTO_TREASURY_EQUITY_PATTERN.test(equityTrade)) return null;
  }
  const targetSource = targetAsset ? ASSET_PATTERNS[targetAsset].source : CRYPTO_ASSET_SOURCE;
  const otherAssetSource = targetAsset
    ? (Object.keys(ASSET_PATTERNS) as Asset[])
      .filter((asset) => asset !== targetAsset)
      .map((asset) => ASSET_PATTERNS[asset].source)
      .join("|")
    : null;
  const clauseActionGap = (distance: number) => String.raw`(?:(?!\b(?:${TRADE_ACTION_SOURCE}|as|while|but|whereas)\b)[^!?,;:]){0,${distance}}`;
  const semanticGap = (distance: number) => String.raw`(?:(?!\b(?:${TRADE_ACTION_SOURCE}|as|while|but|whereas)\b${otherAssetSource ? `|(?:${otherAssetSource})` : ""})[^!?,;:]){0,${distance}}`;
  const directActions: ReadonlyArray<readonly [AiAction, RegExp]> = [
    ["buy", new RegExp(String.raw`\b(?:buy|buys|buying|bought|purchase|purchases|purchased|adds?|added|accumulates?|accumulated)\b${semanticGap(80)}(?:${targetSource})|(?:${targetSource})${semanticGap(80)}\b(?:buy|buys|buying|bought|purchase|purchases|purchased|adds?|added|accumulates?|accumulated)\b`, "iu")],
    ["sell", new RegExp(String.raw`\b(?:sell|sells|selling|sold|offload|offloads|offloaded|dump|dumps|dumped|divests?|divested)\b${semanticGap(80)}(?:${targetSource})|(?:${targetSource})${semanticGap(80)}\b(?:sell|sells|selling|sold|sales?|offload|offloads|offloaded|dump|dumps|dumped|divests?|divested)\b`, "iu")],
    ["withdraw", new RegExp(String.raw`\b(?:withdraw|withdraws|withdrew|outflow|outflows|redemption|redemptions)\b${semanticGap(80)}(?:${targetSource})|(?:${targetSource})${semanticGap(80)}\b(?:withdraw|withdraws|withdrew|outflow|outflows|redemption|redemptions)\b`, "iu")],
  ];
  const direct = directActions
    .map(([candidate, pattern]) => ({ candidate, index: text.search(pattern) }))
    .filter(({ index }) => index >= 0)
    .sort((left, right) => left.index - right.index)[0];
  if (direct) return direct.candidate;
  if (targetAsset && otherAssetSource) {
    const coordinatedListAction = text.match(new RegExp(
      String.raw`(?:${targetSource})\s*,\s*(?:${otherAssetSource})\s+\b(buy|buys|buying|purchase|purchases|sales?|selling|outflows?|redemptions?)\b`,
      "iu",
    ))?.[1]?.toLowerCase();
    if (coordinatedListAction) {
      if (/^(?:buy|buys|buying|purchase|purchases)$/u.test(coordinatedListAction)) return "buy";
      if (/^(?:outflow|outflows|redemption|redemptions)$/u.test(coordinatedListAction)) return "withdraw";
      return "sell";
    }
  }
  if (targetAsset) {
    const otherAssets = (Object.keys(ASSET_PATTERNS) as Asset[]).filter((asset) => asset !== targetAsset);
    const otherAssetTrade = otherAssets.some((asset) => new RegExp(
      String.raw`(?:${ASSET_PATTERNS[asset].source})${clauseActionGap(60)}\b${TRADE_ACTION_SOURCE}\b|\b${TRADE_ACTION_SOURCE}\b${clauseActionGap(60)}(?:${ASSET_PATTERNS[asset].source})`, "iu",
    ).test(text));
    if (otherAssetTrade) return null;
  }
  if (NON_CRYPTO_SELL_PATTERN.test(text)) return null;
  return ACTION_PATTERNS.find(([, pattern]) => pattern.test(text))?.[0] ?? null;
}

function inferActorType(text: string): AiActorType {
  if (REGULATOR_PATTERN.test(text)) return "regulator";
  if (ETF_PATTERN.test(text)) return "ETF";
  if (FUND_PATTERN.test(text)) return "fund";
  if (INSTITUTION_PATTERN.test(text) || /\b(?:Harvard|Yale)\b/iu.test(text)) return "institution";
  if (EXCHANGE_PATTERN.test(text)) return "exchange";
  if (WHALE_PATTERN.test(text)) return "whale";
  if (INVESTOR_PATTERN.test(text)) return "investor";
  if (COMPANY_PATTERN.test(text)) return "company";
  if (PROTOCOL_PATTERN.test(text)) return "protocol";
  if (/\b(?:government|ministry|congress|senate)\b|уряд|правительств/iu.test(text)) return "government";
  return "unknown";
}

function inferDirection(action: AiAction | null, text: string): AiDirection {
  if (/\b(?:outflow|outflows|redemption|redemptions)\b|відплив|відтік|отток/iu.test(text)) return "outflow";
  if (/\b(?:inflow|inflows)\b|приплив|притік|приток/iu.test(text)) return "inflow";
  if (action && ["buy", "invest", "deposit", "fund", "raise", "stake"].includes(action)) return "inflow";
  if (action && ["sell", "divest", "withdraw", "liquidate", "unstake"].includes(action)) return "outflow";
  if (action && ["approve", "reject", "file", "sue", "hack", "exploit", "list", "delist", "upgrade", "acquire"].includes(action)) return "neutral";
  return "unknown";
}

function assetRole(event: SemanticEventInput, asset: Asset | null): SemanticEventMatch["assetRole"] {
  if (!asset || !event.assets.includes(asset)) return "unknown";
  if (ASSET_PATTERNS[asset].test(event.title)) return "primary";
  return "secondary";
}

function topicMatches(
  topic: AiTopic,
  text: string,
  action: AiAction | null,
  direction: AiDirection,
  actor: AiActorType,
  magnitude: AiMagnitude,
  role: SemanticEventMatch["assetRole"],
  targetAsset: Asset | null,
): boolean {
  const targetSource = targetAsset ? ASSET_PATTERNS[targetAsset].source : CRYPTO_ASSET_SOURCE;
  const clauseGap = (distance: number) => String.raw`(?:(?!\b(?:as|while|but|whereas)\b)[^,;:]){0,${distance}}`;
  const targeted = (subjectSource: string, distance: number) => new RegExp(
    String.raw`(?:${targetSource})${clauseGap(distance)}(?:${subjectSource})|(?:${subjectSource})${clauseGap(distance)}(?:${targetSource})`,
    "iu",
  ).test(text);
  switch (topic) {
    case "large_investment":
      return role === "primary" && magnitude === "large" && (action === "buy" || action === "invest");
    case "institutional_purchase":
      return role === "primary" && direction === "inflow" && (action === "buy" || action === "invest")
        && ["institution", "fund", "ETF", "company", "investor", "whale"].includes(actor);
    case "institutional_selling":
      return role === "primary" && direction === "outflow" && ["sell", "divest", "withdraw", "liquidate"].includes(action ?? "")
        && ["institution", "fund", "ETF", "company", "investor", "whale"].includes(actor);
    case "capital_inflow":
      return role === "primary" && direction === "inflow" && !["fund", "raise", "acquire"].includes(action ?? "");
    case "capital_outflow":
      return role === "primary" && direction === "outflow";
    case "funding":
      return action === "fund" || action === "raise";
    case "acquisition":
      return action === "acquire";
    case "liquidation":
      return action === "liquidate";
    case "etf_inflow":
      return ETF_PATTERN.test(text) && direction === "inflow"
        && !/\b(?:end|ends|ended|ending)\b[^,.;:]{0,35}\binflows?\s+streak\b/iu.test(text)
        && targeted(String.raw`\b(?:ETF|ETFs|exchange[- ]traded funds?)\b`, 40)
        && targeted(String.raw`\binflows?\b`, 80);
    case "etf_outflow":
      return ETF_PATTERN.test(text) && direction === "outflow"
        && !/\b(?:end|ends|ended|ending)\b[^,.;:]{0,35}\boutflows?\s+streak\b/iu.test(text)
        && targeted(String.raw`\b(?:ETF|ETFs|exchange[- ]traded funds?)\b`, 40)
        && targeted(String.raw`\b(?:outflows?|redemptions?)\b`, 80);
    case "etf":
      return ETF_PATTERN.test(text);
    case "etf_approval":
      return ETF_PATTERN.test(text) && action === "approve";
    case "etf_rejection":
      return ETF_PATTERN.test(text) && action === "reject";
    case "etf_delay":
      return ETF_PATTERN.test(text)
        && /\b(?:delay|delays|delayed|postpone|postpones|postponed|defer|defers|deferred)\b/iu.test(text);
    case "sec":
      return REGULATOR_PATTERN.test(text);
    case "sec_filings":
      return /\b(?:SEC\s+filings?|8-K|10-K|10-Q|S-1|19b-4|registration statement)\b/iu.test(text);
    case "regulatory_approval":
      return (REGULATOR_PATTERN.test(text) || ETF_PATTERN.test(text)) && action === "approve";
    case "regulatory_enforcement":
      return REGULATOR_PATTERN.test(text)
        && /\b(?:enforcement|crackdown|charges?|fines?|penalt(?:y|ies)|sanctions?|sues?|sued|lawsuits?|litigation)\b/iu.test(text);
    case "hack":
      return HACK_INCIDENT_PATTERN.test(text) && !HACK_NON_INCIDENT_PATTERN.test(text)
        && targeted(String.raw`\b(?:hack|hacks|hacked|hacking|exploit|exploits|exploited|security breach|data breach)\b`, 80);
    case "listing":
      return action === "list";
    case "lawsuit":
      return action === "sue";
    case "macro":
      return /\b(?:macro(?:economic)?|inflation|interest rates?|central banks?|GDP|payrolls?)\b/iu.test(text);
    case "fed":
      return /\b(?:Federal Reserve|Fed|FOMC)\b/iu.test(text);
    case "fed_rate_hike":
      return /\b(?:Federal Reserve|Fed|FOMC)\b/iu.test(text)
        && /\b(?:rate\s+)?(?:hike|hikes|hiked|raise|raises|raised|increase|increases|increased|tightening)\b/iu.test(text);
    case "fed_rate_cut":
      return /\b(?:Federal Reserve|Fed|FOMC)\b/iu.test(text)
        && /\b(?:rate\s+)?(?:cut|cuts|lower|lowers|lowered|decrease|decreases|decreased|easing)\b/iu.test(text);
    case "cpi":
      return /\b(?:CPI|consumer price index|inflation report)\b/iu.test(text);
    case "upgrade":
      return action === "upgrade";
    case "staking":
      return action === "stake" || action === "unstake";
  }
}

function fail(base: Omit<SemanticEventMatch, "matched" | "confidence" | "relevanceScore" | "reasons">, reason: string): SemanticEventMatch {
  return { ...base, matched: false, confidence: 0, relevanceScore: 0, reasons: [reason] };
}

function actionCompatible(intent: AiSearchIntent, actual: AiAction | null): boolean {
  if (!intent.action) return true;
  const topicActions: Partial<Record<AiTopic, readonly AiAction[]>> = {
    large_investment: ["buy", "invest"],
    institutional_purchase: ["buy", "invest"],
    institutional_selling: ["sell", "divest", "withdraw", "liquidate"],
    capital_inflow: ["buy", "invest", "deposit"],
    capital_outflow: ["sell", "divest", "withdraw", "liquidate"],
    funding: ["fund", "raise"],
    etf_inflow: ["buy", "invest", "deposit"],
    etf_outflow: ["sell", "divest", "withdraw"],
    etf_approval: ["approve"],
    etf_rejection: ["reject"],
    regulatory_approval: ["approve"],
    hack: ["hack", "exploit"],
  };
  const compatible = intent.topic ? topicActions[intent.topic] : undefined;
  return compatible ? compatible.includes(actual as AiAction) : actual === intent.action;
}

const DIRECTIONAL_TOPICS = new Set<AiTopic>([
  "large_investment", "institutional_purchase", "institutional_selling", "capital_inflow", "capital_outflow",
  "funding", "etf_inflow", "etf_outflow",
]);

const TOPIC_CATEGORY_ALIASES: Partial<Record<AiTopic, readonly string[]>> = {
  sec: ["legal", "legal_action", "official_decision", "policy_statement", "regulation"],
  sec_filings: ["legal", "official_decision", "regulation"],
  regulatory_approval: ["official_decision", "policy_statement", "regulation"],
  regulatory_enforcement: ["legal", "legal_action", "official_decision", "regulation"],
  etf: ["etf"], etf_approval: ["etf", "official_decision", "regulation"],
  etf_rejection: ["etf", "official_decision", "regulation"], etf_delay: ["etf", "official_decision", "regulation"],
  etf_inflow: ["etf"], etf_outflow: ["etf"],
  hack: ["hack", "security", "security_event"],
  macro: ["macro"], fed: ["macro"], fed_rate_hike: ["macro"], fed_rate_cut: ["macro"], cpi: ["macro"],
  institutional_purchase: ["institutional", "institutional_adoption"],
  institutional_selling: ["institutional", "institutional_adoption"],
  large_investment: ["institutional", "institutional_adoption"],
};

function relevanceScore(event: SemanticEventInput, intent: AiSearchIntent, actual: {
  role: SemanticEventMatch["assetRole"];
  action: AiAction | null;
  direction: AiDirection;
  actorType: AiActorType;
  magnitude: AiMagnitude;
}): number {
  let score = intent.topic ? 50 : 20;
  if (actual.role === "primary") score += 20;
  else if (actual.role === "secondary") score += 5;
  if (intent.topic && TOPIC_CATEGORY_ALIASES[intent.topic]?.includes(event.category)) score += 10;
  if (intent.action && actual.action === intent.action) score += 10;
  else if (intent.action && actionCompatible(intent, actual.action)) score += 7;
  if (intent.direction !== "unknown" && actual.direction === intent.direction) score += 8;
  if (intent.actorType !== "unknown" && actual.actorType === intent.actorType) score += 8;
  else if (intent.actorType !== "unknown") score += 5;
  if (intent.magnitude !== "unknown" && actual.magnitude === intent.magnitude) score += 4;
  return score;
}

/**
 * Pure deterministic runtime classifier. It receives one already-bounded public
 * analytics row and a validated intent; it never calls an AI provider or a DB.
 */
export function classifySemanticEvent(event: SemanticEventInput, intent: AiSearchIntent): SemanticEventMatch {
  const text = event.title.normalize("NFKC");
  const amount = extractSemanticAmount(text);
  const action = inferAction(text, intent.asset);
  const direction = inferDirection(action, text);
  const actorType = inferActorType(text);
  const role = assetRole(event, intent.asset);
  const strongPhrase = STRONG_LARGE_PATTERN.test(text);
  const magnitude: AiMagnitude = amount?.normalizedUsd !== null && amount?.normalizedUsd !== undefined
    ? amount.normalizedUsd >= LARGE_INVESTMENT_USD_THRESHOLD ? "large" : "standard"
    : strongPhrase ? "large" : "unknown";
  const base = { assetRole: role, amount, magnitude, actorType, action, direction };

  if (intent.asset && !event.assets.includes(intent.asset)) return fail(base, "asset-not-related");
  if (intent.asset && intent.assetRole !== "any" && role !== intent.assetRole) return fail(base, `asset-role-${role}`);
  if (intent.entity && !text.toLocaleLowerCase("en-US").includes(intent.entity.toLocaleLowerCase("en-US"))) {
    return fail(base, "entity-not-present");
  }
  const compatibleActor = intent.actorType === actorType
    || (intent.actorType === "institution" && ["institution", "fund", "ETF"].includes(actorType))
    || (intent.actorType === "institution" && ["institutional_purchase", "institutional_selling"].includes(intent.topic ?? "") && actorType === "company")
    || (intent.actorType === "investor" && ["investor", "whale", "institution", "fund", "ETF", "company"].includes(actorType));
  if (intent.actorType !== "unknown" && !compatibleActor) return fail(base, "actor-type-mismatch");
  if (!actionCompatible(intent, action)) return fail(base, "action-mismatch");
  const directionIsSemantic = !intent.topic || DIRECTIONAL_TOPICS.has(intent.topic);
  if (directionIsSemantic && intent.direction !== "unknown" && direction !== intent.direction) return fail(base, "direction-mismatch");
  if (intent.magnitude !== "unknown" && magnitude !== intent.magnitude) return fail(base, "magnitude-mismatch");
  if (intent.amount) {
    if (!amount || amount.currency !== intent.amount.currency || amount.value < intent.amount.value) return fail(base, "amount-below-request");
  }
  if (intent.topic && !topicMatches(intent.topic, text, action, direction, actorType, magnitude, role, intent.asset)) {
    return fail(base, "topic-meaning-mismatch");
  }

  const hasSemanticMeaning = Boolean(intent.topic || intent.action || intent.direction !== "unknown" || intent.magnitude !== "unknown" || intent.actorType !== "unknown");
  let confidence = hasSemanticMeaning ? 0.8 : 1;
  const reasons = ["deterministic-semantic-match"];
  if (intent.magnitude === "large" || intent.topic === "large_investment") {
    if (amount?.normalizedUsd && amount.normalizedUsd >= LARGE_INVESTMENT_USD_THRESHOLD) {
      confidence = 1;
      reasons.push("explicit-usd-amount-at-least-50m");
    } else if (strongPhrase) {
      confidence = SEMANTIC_CONFIDENCE_THRESHOLD;
      reasons.push("strong-large-phrase-without-explicit-usd-amount");
    }
  }
  if (intent.topic && ["sec", "sec_filings", "etf", "hack"].includes(intent.topic)) confidence = 1;
  return {
    ...base,
    matched: confidence >= SEMANTIC_CONFIDENCE_THRESHOLD,
    confidence: round(confidence),
    relevanceScore: relevanceScore(event, intent, { role, action, direction, actorType, magnitude }),
    reasons,
  };
}

export function requiresSemanticMatching(intent: AiSearchIntent): boolean {
  return Boolean(
    intent.topic || intent.action || intent.direction !== "unknown" || intent.magnitude !== "unknown"
    || intent.actorType !== "unknown" || intent.entity || intent.amount || Boolean(intent.asset && intent.assetRole !== "any"),
  );
}
