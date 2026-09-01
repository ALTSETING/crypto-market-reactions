import { describe, expect, it } from "vitest";

import { runAnalytics } from "@/lib/ai-search/analytics";
import { groupIndependentEvents } from "@/lib/ai-search/event-dedup";
import type { SemanticEventMatch } from "@/lib/ai-search/semantic-matcher";
import type { AiSearchIntent, AnalyticsEvent } from "@/types/ai-search";

const emptyReactions = (): AnalyticsEvent["reactionV2"] => ({
  BTC: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
  ETH: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
  SOL: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
});

function event(
  eventId: string,
  title: string,
  publishedAt: string,
  asset: "BTC" | "ETH" | "SOL" = "BTC",
  sourceClass: AnalyticsEvent["sourceClass"] = "news_media",
  reaction = 1,
): AnalyticsEvent {
  const reactionV2 = emptyReactions();
  reactionV2[asset]["24h"] = reaction;
  return {
    eventId,
    slug: eventId,
    title,
    publishedAt,
    assets: [asset],
    primaryAsset: asset,
    category: "news",
    sourceClass,
    sentiment: null,
    importance: null,
    reactionV2,
  };
}

function intent(topic: NonNullable<AiSearchIntent["topic"]>, asset: "BTC" | "ETH" | "SOL" = "BTC"): AiSearchIntent {
  return {
    intent: "aggregate",
    asset,
    dateFrom: null,
    dateTo: null,
    category: null,
    topic,
    actorType: "unknown",
    action: null,
    direction: "unknown",
    magnitude: "unknown",
    amount: null,
    entity: null,
    assetRole: "primary",
    sourceClass: null,
    sentiment: null,
    reactionSign: null,
    importance: null,
    horizon: "24h",
    metric: "mean",
    sort: "newest",
    groupBy: "none",
    comparison: null,
    limit: 50,
  };
}

interface DecisionCase {
  label: string;
  topic: NonNullable<AiSearchIntent["topic"]>;
  left: [string, string, ("BTC" | "ETH" | "SOL")?];
  right: [string, string, ("BTC" | "ETH" | "SOL")?];
  independent: number;
}

const decisions: DecisionCase[] = [
  { label: "same BlackRock ETF approval", topic: "etf_approval", left: ["SEC approves BlackRock spot Bitcoin ETF", "2024-01-10T12:00:00Z"], right: ["BlackRock Bitcoin ETF wins SEC approval", "2024-01-10T13:00:00Z"], independent: 1 },
  { label: "same WisdomTree ETF rejection", topic: "etf_rejection", left: ["SEC rejects WisdomTree spot Bitcoin ETF", "2022-01-20T10:00:00Z"], right: ["WisdomTree Bitcoin ETF rejected by SEC", "2022-01-20T11:00:00Z"], independent: 1 },
  { label: "same Coinbase lawsuit", topic: "lawsuit", left: ["SEC sues Coinbase in crypto enforcement action", "2023-06-06T14:00:00Z"], right: ["Coinbase sued by SEC in major crypto lawsuit", "2023-06-06T15:00:00Z"], independent: 1 },
  { label: "same Drift hack and repayment update", topic: "hack", left: ["Drift to repay users following $295M Solana hack", "2026-04-01T09:00:00Z", "SOL"], right: ["Solana-based Drift hit by $285M exploit", "2026-03-31T18:00:00Z", "SOL"], independent: 1 },
  { label: "same Nomad bridge hack", topic: "hack", left: ["Nomad and Solana bridge hacked for $190M", "2022-08-02T01:00:00Z", "SOL"], right: ["Solana and Nomad bridge fall prey to $190 million exploit", "2022-08-02T03:00:00Z", "SOL"], independent: 1 },
  { label: "same Taiko breach update", topic: "hack", left: ["Taiko warns users after bridge security breach", "2025-05-01T09:00:00Z", "ETH"], right: ["Taiko halts bridge following exploit", "2025-05-02T09:00:00Z", "ETH"], independent: 1 },
  { label: "same Kelp exploit update", topic: "hack", left: ["Kelp DAO exploited for $292M", "2026-02-01T08:00:00Z", "ETH"], right: ["Arbitrum freezes $71M tied to Kelp exploit", "2026-02-03T08:00:00Z", "ETH"], independent: 1 },
  { label: "same CPI release", topic: "cpi", left: ["Bitcoin rises after CPI inflation report shows 3.2%", "2024-02-13T13:31:00Z"], right: ["CPI comes in at 3.2% as Bitcoin gains", "2024-02-13T14:00:00Z"], independent: 1 },
  { label: "same Fed rate cut", topic: "fed_rate_cut", left: ["Bitcoin slips as Fed cuts rates by 25 bps", "2024-12-18T19:01:00Z"], right: ["Fed delivers 25 bps rate cut and Bitcoin wavers", "2024-12-18T19:20:00Z"], independent: 1 },
  { label: "same BitMine purchase", topic: "institutional_purchase", left: ["BitMine buys $52M in Ether", "2026-01-04T08:00:00Z", "ETH"], right: ["Tom Lee's BitMine makes $52 million ETH purchase", "2026-01-04T09:00:00Z", "ETH"], independent: 1 },
  { label: "same SharpLink purchase", topic: "institutional_purchase", left: ["SharpLink buys $252M of Ethereum", "2025-07-10T08:00:00Z", "ETH"], right: ["SharpLink adds Ether in $252 million purchase", "2025-07-10T11:00:00Z", "ETH"], independent: 1 },
  { label: "same ETF inflow day and amount", topic: "etf_inflow", left: ["Bitcoin ETFs post $500M daily inflows", "2025-01-08T08:00:00Z"], right: ["Spot BTC ETF inflows reach $500 million", "2025-01-08T18:00:00Z"], independent: 1 },
  { label: "same ETF outflow day and amount", topic: "etf_outflow", left: ["Bitcoin ETFs record $240M outflows", "2025-01-09T08:00:00Z"], right: ["Spot BTC ETF outflows total $240 million", "2025-01-09T18:00:00Z"], independent: 1 },
  { label: "different ETF inflow days", topic: "etf_inflow", left: ["Bitcoin ETFs post $500M daily inflows", "2025-01-08T08:00:00Z"], right: ["Bitcoin ETFs post $500M daily inflows", "2025-01-09T08:00:00Z"], independent: 2 },
  { label: "different ETF flow amounts on one day", topic: "etf_inflow", left: ["Bitcoin ETFs post $500M daily inflows", "2025-01-08T08:00:00Z"], right: ["Bitcoin ETFs post $600M daily inflows", "2025-01-08T18:00:00Z"], independent: 2 },
  { label: "inflow and outflow are different actions", topic: "etf", left: ["Bitcoin ETF inflows reach $300M", "2025-01-08T08:00:00Z"], right: ["Bitcoin ETF outflows reach $300M", "2025-01-08T09:00:00Z"], independent: 2 },
  { label: "BitMine purchases on different dates", topic: "institutional_purchase", left: ["BitMine buys $52M in Ether", "2026-01-01T08:00:00Z", "ETH"], right: ["BitMine buys $52M in Ether", "2026-01-05T08:00:00Z", "ETH"], independent: 2 },
  { label: "BitMine purchases with different amounts", topic: "institutional_purchase", left: ["BitMine buys $52M in Ether", "2026-01-01T08:00:00Z", "ETH"], right: ["BitMine buys $72M in Ether", "2026-01-01T12:00:00Z", "ETH"], independent: 2 },
  { label: "different institutional purchasers", topic: "institutional_purchase", left: ["BitMine buys $52M in Ether", "2026-01-01T08:00:00Z", "ETH"], right: ["SharpLink buys $52M in Ether", "2026-01-01T12:00:00Z", "ETH"], independent: 2 },
  { label: "different ETF sponsors", topic: "etf_rejection", left: ["SEC rejects WisdomTree spot Bitcoin ETF", "2022-01-20T10:00:00Z"], right: ["SEC rejects VanEck spot Bitcoin ETF", "2022-01-20T11:00:00Z"], independent: 2 },
  { label: "different SEC defendants", topic: "lawsuit", left: ["SEC sues Coinbase over crypto trading", "2023-06-06T10:00:00Z"], right: ["SEC sues Binance over crypto trading", "2023-06-06T11:00:00Z"], independent: 2 },
  { label: "different hack entities", topic: "hack", left: ["Binance hacked for $40M", "2023-01-01T10:00:00Z"], right: ["Coinbase hacked for $40M", "2023-01-01T11:00:00Z"], independent: 2 },
  { label: "same entity hacks months apart", topic: "hack", left: ["Binance hot wallet hacked for $40M", "2023-01-01T10:00:00Z"], right: ["Binance bridge hacked for $40M", "2023-03-01T11:00:00Z"], independent: 2 },
  { label: "Fed forecast and decision", topic: "fed", left: ["Markets expect Fed rate cut this week", "2024-12-18T08:00:00Z"], right: ["Fed cuts rates as markets react", "2024-12-18T19:00:00Z"], independent: 2 },
  { label: "CPI releases on different dates", topic: "cpi", left: ["CPI inflation report shows 3.2%", "2024-02-13T13:30:00Z"], right: ["CPI inflation report shows 3.2%", "2024-03-12T13:30:00Z"], independent: 2 },
  { label: "different asset context", topic: "hack", left: ["Nomad bridge hacked for $190M", "2022-08-02T01:00:00Z", "SOL"], right: ["Nomad bridge hacked for $190M", "2022-08-02T02:00:00Z", "ETH"], independent: 2 },
];

describe("historical real-event grouping decisions", () => {
  it.each(decisions)("classifies $label", ({ topic, left, right, independent }) => {
    const asset = left[2] ?? "BTC";
    const events = [event("a", left[0], left[1], asset), event("b", right[0], right[1], right[2] ?? asset)];
    expect(groupIndependentEvents(events, intent(topic, asset), new Map()).representatives).toHaveLength(independent);
  });

  it("is byte-deterministic for repeated input", () => {
    const events = [
      event("a", "SEC approves BlackRock spot Bitcoin ETF", "2024-01-10T12:00:00Z"),
      event("b", "BlackRock Bitcoin ETF wins SEC approval", "2024-01-10T13:00:00Z"),
    ];
    const serialize = () => JSON.stringify(groupIndependentEvents(events, intent("etf_approval"), new Map()).groups);
    expect(serialize()).toBe(serialize());
  });

  it("collapses a verified four-article ETF launch while retaining the earlier filing", () => {
    const events = [
      event("trading-a", "Ethereum news: BlackRock’s staked ether ETF draws $15 million in first-day trading", "2026-03-13T06:23:09Z", "ETH"),
      event("trading-b", "BlackRock’s Staked ETH ETF Sees $15.5M on Debut", "2026-03-13T00:00:00Z", "ETH"),
      event("launch-a", "BlackRock debuts staked ether ETF as demand grows for yield in crypto funds", "2026-03-12T12:00:00Z", "ETH"),
      event("launch-b", "BlackRock Launches Staked Ethereum ETF Offering Yield", "2026-03-12T00:00:00Z", "ETH"),
      event("filing", "Bitcoin ETF Giant BlackRock Files to Launch Ethereum Staking ETF", "2025-12-08T18:15:12Z", "ETH"),
    ];
    const result = groupIndependentEvents(events, intent("etf", "ETH"), new Map());
    expect(result.groups.map(({ members }) => members.map(({ eventId }) => eventId))).toEqual([
      ["launch-b", "launch-a", "trading-b", "trading-a"],
      ["filing"],
    ]);
  });

  it("keeps a hack-related lawsuit separate but joins an explicitly linked later repayment update", () => {
    const events = [
      event("repay", "How Solana Exchange Drift Plans to Repay Users After $295 Million Crypto Hack", "2026-05-05T21:25:23Z", "SOL"),
      event("lawsuit", "Circle Hit With Class Action Suit Over $280M Drift Hack", "2026-04-17T00:00:00Z", "SOL"),
      event("hack", "Morning Minute: North Korea Hacks Drift for $285M", "2026-04-06T12:18:33Z", "SOL"),
    ];
    const result = groupIndependentEvents(events, intent("hack", "SOL"), new Map());
    expect(result.groups.map(({ members }) => members.map(({ eventId }) => eventId))).toEqual([
      ["hack", "repay"],
      ["lawsuit"],
    ]);
  });

  it("chooses official sources, then earliest publication, then relevance, without using reaction", () => {
    const events = [
      event("news-high-reaction", "SEC approves BlackRock spot Bitcoin ETF", "2024-01-10T09:00:00Z", "BTC", "news_media", 99),
      event("official-later", "BlackRock Bitcoin ETF wins SEC approval", "2024-01-10T10:00:00Z", "BTC", "official_announcement", -3),
      event("official-latest", "BlackRock spot Bitcoin ETF receives SEC approval", "2024-01-10T11:00:00Z", "BTC", "official_announcement", 40),
    ];
    const result = groupIndependentEvents(events, intent("etf_approval"), new Map());
    expect(result.representatives.map(({ eventId }) => eventId)).toEqual(["official-later"]);
  });

  it("uses semantic relevance only after source class and publication time", () => {
    const events = [
      event("low", "SEC approves BlackRock spot Bitcoin ETF", "2024-01-10T10:00:00Z", "BTC", "news_media"),
      event("high", "BlackRock Bitcoin ETF wins SEC approval", "2024-01-10T10:00:00Z", "BTC", "news_media"),
    ];
    const match = (relevanceScore: number): SemanticEventMatch => ({ matched: true, confidence: 1, relevanceScore, reasons: [], assetRole: "primary", amount: null, magnitude: "standard", actorType: "ETF", action: "approve", direction: "neutral" });
    const result = groupIndependentEvents(events, intent("etf_approval"), new Map([["low", match(1)], ["high", match(5)]]));
    expect(result.representatives[0].eventId).toBe("high");
  });

  it("reports independent sample, groups, citation group size, and post-dedup entity concentration", () => {
    const events = [
      event("bm-a", "Treasury firm BitMine buys $52M in Ether", "2026-01-01T08:00:00Z", "ETH", "news_media", 9),
      event("bm-a-copy", "Ethereum treasury firm BitMine makes $52 million ETH purchase", "2026-01-01T09:00:00Z", "ETH", "official_announcement", 1),
      event("bm-b", "Treasury firm BitMine buys $72M in Ether", "2026-01-05T08:00:00Z", "ETH", "news_media", 3),
      event("sharp", "Treasury firm SharpLink buys $80M in Ether", "2026-01-06T08:00:00Z", "ETH", "news_media", -1),
    ];
    const result = runAnalytics(events, { ...intent("institutional_purchase", "ETH"), action: "buy", direction: "inflow" });
    expect(result).toMatchObject({
      kind: "scalar",
      sampleSize: 3,
      value: 1,
      topicFilter: {
        matchedSampleSize: 4,
        independentEventCount: 3,
        duplicateGroupCount: 1,
        largestDuplicateGroup: 2,
        largestEntity: "bitmine",
        largestEntityShare: 66.67,
        entityConcentrationWarning: true,
      },
    });
    expect(result.citations).toContainEqual(expect.objectContaining({ eventId: "bm-a-copy", groupSize: 2 }));
    expect(result.citations.map(({ eventId }) => eventId)).not.toContain("bm-a");

    const rawIntent = { ...intent("institutional_purchase", "ETH"), topic: null, action: null, direction: "unknown" as const, assetRole: "any" as const };
    expect(runAnalytics(events, rawIntent)).toMatchObject({ kind: "scalar", sampleSize: 4, value: 3 });
    expect(runAnalytics(events, { ...rawIntent, metric: "median" })).toMatchObject({ kind: "scalar", sampleSize: 4, value: 2 });
    expect(runAnalytics(events, { ...rawIntent, metric: "sign_share" })).toMatchObject({ kind: "share", sampleSize: 4, positivePercent: 75 });
    expect(runAnalytics(events, { ...intent("institutional_purchase", "ETH"), action: "buy", direction: "inflow", metric: "median" })).toMatchObject({ kind: "scalar", sampleSize: 3, value: 1 });
    expect(runAnalytics(events, { ...intent("institutional_purchase", "ETH"), action: "buy", direction: "inflow", metric: "sign_share" })).toMatchObject({ kind: "share", sampleSize: 3, positivePercent: 66.666667 });
  });
});
