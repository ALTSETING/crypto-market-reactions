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
  regulatory_approval: [
    /\b(?:SEC|CFTC|regulator(?:s|y)?|Securities\s+and\s+Exchange\s+Commission)\b[^.]{0,80}\b(?:approve|approves|approved|approvals?|authori[sz](?:e|es|ed|ation))\b/iu,
    /\b(?:approve|approves|approved|approvals?|authori[sz](?:e|es|ed|ation))\b[^.]{0,80}\b(?:SEC|CFTC|regulator(?:s|y)?|Securities\s+and\s+Exchange\s+Commission)\b/iu,
    /\b(?:ETFs?|exchange[- ]traded\s+funds?)\b[^.]{0,80}\b(?:approve|approves|approved|approvals?)\b/iu,
    /\b(?:approve|approves|approved|approvals?)\b[^.]{0,80}\b(?:ETFs?|exchange[- ]traded\s+funds?)\b/iu,
  ],
  regulatory_enforcement: [
    /\b(?:SEC|CFTC|regulator(?:s|y)?|Securities\s+and\s+Exchange\s+Commission)\b[^.]{0,80}\b(?:enforcement|crackdown|charges?|fines?|penalt(?:y|ies)|sanctions?|sues?|lawsuits?)\b/iu,
    /\b(?:enforcement|crackdown|charges?|fines?|penalt(?:y|ies)|sanctions?|sues?|lawsuits?)\b[^.]{0,80}\b(?:SEC|CFTC|regulator(?:s|y)?|Securities\s+and\s+Exchange\s+Commission)\b/iu,
  ],
  etf: [
    /\bETFs?\b/iu,
    /\bexchange[- ]traded\s+funds?\b/iu,
  ],
  etf_approval: [
    /\b(?:ETFs?|exchange[- ]traded\s+funds?)\b[^.]{0,80}\b(?:approve|approves|approved|approvals?|greenlight(?:s|ed)?)\b/iu,
    /\b(?:approve|approves|approved|approvals?|greenlight(?:s|ed)?)\b[^.]{0,80}\b(?:ETFs?|exchange[- ]traded\s+funds?)\b/iu,
  ],
  etf_rejection: [
    /\b(?:ETFs?|exchange[- ]traded\s+funds?)\b[^.]{0,80}\b(?:reject|rejects|rejected|denies|denied|rejection)\b/iu,
    /\b(?:reject|rejects|rejected|denies|denied|rejection)\b[^.]{0,80}\b(?:ETFs?|exchange[- ]traded\s+funds?)\b/iu,
  ],
  etf_delay: [
    /\b(?:ETFs?|exchange[- ]traded\s+funds?)\b[^.]{0,80}\b(?:delay|delays|delayed|postpone|postpones|postponed|defer|defers|deferred)\b/iu,
    /\b(?:delay|delays|delayed|postpone|postpones|postponed|defer|defers|deferred)\b[^.]{0,80}\b(?:ETFs?|exchange[- ]traded\s+funds?)\b/iu,
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
  fed_rate_hike: [
    /\b(?:Fed(?:eral Reserve)?|FOMC)\b[^.]{0,80}\b(?:rate\s+)?(?:hike|hikes|hiked|raise|raises|raised|increase|increases|increased|tightening)\b/iu,
    /\b(?:rate\s+)?(?:hike|hikes|hiked|raise|raises|raised|increase|increases|increased|tightening)\b[^.]{0,80}\b(?:Fed(?:eral Reserve)?|FOMC)\b/iu,
  ],
  fed_rate_cut: [
    /\b(?:Fed(?:eral Reserve)?|FOMC)\b[^.]{0,80}\b(?:rate\s+)?(?:cut|cuts|lower|lowers|lowered|decrease|decreases|decreased|easing)\b/iu,
    /\b(?:rate\s+)?(?:cut|cuts|lower|lowers|lowered|decrease|decreases|decreased|easing)\b[^.]{0,80}\b(?:Fed(?:eral Reserve)?|FOMC)\b/iu,
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
