import "server-only";

import type { AiTopic, AnalyticsEvent } from "@/types/ai-search";

const TOPIC_PATTERNS: Record<AiTopic, readonly RegExp[]> = {
  sec: [
    /\bSEC\b/iu,
    /\bSecurities\s+and\s+Exchange\s+Commission\b/iu,
  ],
  sec_filings: [
    /\bSEC\s+filings?\b/iu,
    /\bSecurities\s+and\s+Exchange\s+Commission\b[^.]{0,80}\bfilings?\b/iu,
    /\b(?:8-K|10-K|10-Q|S-1|19b-4)\b/iu,
    /\bregistration\s+statement\b/iu,
  ],
  etf: [
    /\bETFs?\b/iu,
    /\bexchange[- ]traded\s+funds?\b/iu,
  ],
  hack: [
    /\bhack(?:ed|ing|s)?\b/iu,
    /\bexploit(?:ed|s|ing)?\b/iu,
    /\bsecurity\s+breach\b/iu,
    /\bcyber(?:attack| attack)\b/iu,
  ],
  listing: [
    /\b(?:listing|listed|lists)\b/iu,
    /\btrading\s+debut\b/iu,
  ],
  lawsuit: [
    /\blawsuits?\b/iu,
    /\blitigation\b/iu,
    /\b(?:sues|sued)\b/iu,
  ],
  macro: [
    /\bmacroeconomic\b/iu,
    /\binflation\b/iu,
    /\binterest\s+rates?\b/iu,
    /\bcentral\s+banks?\b/iu,
    /\b(?:GDP|jobs report|payrolls?)\b/iu,
  ],
  fed: [
    /\bFederal\s+Reserve\b/iu,
    /\bFed\b/iu,
    /\bFOMC\b/iu,
  ],
  cpi: [
    /\bCPI\b/iu,
    /\bconsumer\s+price\s+index\b/iu,
    /\binflation\s+report\b/iu,
  ],
  upgrade: [
    /\bupgrades?\b/iu,
    /\bhard\s+fork\b/iu,
    /\bnetwork\s+update\b/iu,
  ],
  staking: [
    /\bstak(?:e|ed|es|ing)\b/iu,
    /\bproof[- ]of[- ]stake\b/iu,
  ],
  large_investment: [
    /\binvest(?:s|ed|ing)\b/iu,
    /\binvestments?\b(?!\s+(?:gains?|returns?|products?|funds?|vehicles?)\b)/iu,
    /\bfunding\b(?!\s+(?:gap|shortfall|cuts?|pressure|concerns?|crisis|issues?|problems?|needs?)\b)/iu,
    /\bfunded\b/iu,
    /\brais(?:e|es|ed|ing)\b[^.]{0,40}\b(?:million|billion|round|capital|funding)\b/iu,
    /\b(?:purchase|purchases|purchased|buys|bought)\b/iu,
    /\bacqui(?:res?|red|sition|sitions)\b/iu,
    /\btreasury\s+(?:buy|buys|purchase|purchases)\b/iu,
    /\binstitutional\s+(?:buy|buys|purchase|purchases)\b/iu,
  ],
  institutional_purchase: [
    /\binstitutional\s+(?:buy|buys|buyer|purchase|purchases|purchased)\b/iu,
    /\btreasury\s+(?:buy|buys|purchase|purchases|purchased|reserve)\b/iu,
  ],
  institutional_selling: [
    /\binstitutional\s+(?:sell|sells|selling|sales)\b/iu,
    /\b(?:fund|institution|whale|investor)\b[^.]{0,60}\b(?:sell|sells|sold|redemptions?)\b/iu,
  ],
  capital_inflow: [/\b(?:capital\s+)?inflows?\b/iu],
  capital_outflow: [/\b(?:capital\s+)?outflows?\b/iu, /\bredemptions?\b/iu],
  funding: [
    /\bfund(?:ing|ed)\b/iu,
    /\bfundrais(?:e|es|ed|ing)\b/iu,
    /\brais(?:e|es|ed|ing)\b[^.]{0,40}\b(?:million|billion|round|capital)\b/iu,
    /\b(?:seed|Series\s+[A-Z])\s+round\b/iu,
  ],
  acquisition: [
    /\bacqui(?:res?|red|sition|sitions)\b/iu,
    /\btakeovers?\b/iu,
  ],
  liquidation: [/\bliquidat(?:e|es|ed|ion|ions)\b/iu],
  etf_inflow: [/\bETFs?\b[^.]{0,50}\binflows?\b|\binflows?\b[^.]{0,50}\bETFs?\b/iu],
  etf_outflow: [/\bETFs?\b[^.]{0,50}\boutflows?\b|\boutflows?\b[^.]{0,50}\bETFs?\b/iu],
};

export function matchesTopic(event: Pick<AnalyticsEvent, "title">, topic: AiTopic): boolean {
  return TOPIC_PATTERNS[topic].some((pattern) => pattern.test(event.title));
}
