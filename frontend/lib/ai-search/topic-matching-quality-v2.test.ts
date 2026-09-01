import { describe, expect, it } from "vitest";

import { runAnalytics } from "@/lib/ai-search/analytics";
import { MockAiIntentProvider, OpenAiIntentProvider } from "@/lib/ai-search/provider";
import { validateIntent } from "@/lib/ai-search/schema";
import type { AiSearchIntent, AiTopic, AnalyticsEvent } from "@/types/ai-search";
import type { Asset, EventCategory } from "@/types/events";

const provider = new MockAiIntentProvider();

const MATRIX: ReadonlyArray<readonly [string, Asset, AiTopic]> = [
  ["How did BTC react to ETF approvals?", "BTC", "etf_approval"],
  ["Як BTC реагує на схвалення ETF?", "BTC", "etf_approval"],
  ["What happened to BTC after spot ETFs got approved?", "BTC", "etf_approval"],
  ["How does BTC react to ETF outflows?", "BTC", "etf_outflow"],
  ["What happens to BTC when money leaves ETFs?", "BTC", "etf_outflow"],
  ["How did Bitcoin react to ETF inflows?", "BTC", "etf_inflow"],
  ["How did BTC respond when an ETF was rejected?", "BTC", "etf_rejection"],
  ["What happens to BTC when ETF decisions are delayed?", "BTC", "etf_delay"],
  ["Як BTC реагує на позови SEC?", "BTC", "lawsuit"],
  ["How does BTC react to SEC enforcement?", "BTC", "regulatory_enforcement"],
  ["How does ETH react to regulatory approvals?", "ETH", "regulatory_approval"],
  ["Як BTC реагує на регуляторний тиск і санкції?", "BTC", "regulatory_enforcement"],
  ["How did BTC react when the SEC sued an exchange?", "BTC", "lawsuit"],
  ["How does SOL react to regulator enforcement actions?", "SOL", "regulatory_enforcement"],
  ["How does ETH react to institutional buying?", "ETH", "institutional_purchase"],
  ["Як ETH реагує на купівлі китів?", "ETH", "institutional_purchase"],
  ["What does ETH do after large institutional purchases?", "ETH", "institutional_purchase"],
  ["How does ETH react to institutional selling?", "ETH", "institutional_selling"],
  ["How does BTC react when whales accumulate Bitcoin?", "BTC", "institutional_purchase"],
  ["Як SOL реагує на злами?", "SOL", "hack"],
  ["What happens when Solana protocols get hacked?", "SOL", "hack"],
  ["How does BTC react to exchange hacks?", "BTC", "hack"],
  ["How does SOL respond to exploits?", "SOL", "hack"],
  ["How does ETH react to bridge hacks?", "ETH", "hack"],
  ["How does BTC react to Fed rate hikes?", "BTC", "fed_rate_hike"],
  ["Як BTC реагує на підвищення процентних ставок?", "BTC", "fed_rate_hike"],
  ["How does ETH react when the Fed cuts rates?", "ETH", "fed_rate_cut"],
  ["Як BTC реагує на інфляцію та індекс споживчих цін?", "BTC", "cpi"],
  ["How does SOL react to CPI reports?", "SOL", "cpi"],
  ["Як ETH реагує на монетарне посилення?", "ETH", "fed_rate_hike"],
];

describe("AI Topic Matching Quality V2 — 30-query intent matrix", () => {
  it.each(MATRIX)("maps %s", async (question, asset, topic) => {
    await expect(provider.resolve(question)).resolves.toMatchObject({
      status: "ready",
      intent: { asset, topic, horizon: null },
    });
  });

  it.each([
    "What happens to BTC when money leaves ETFs?",
    "What happens when Solana protocols get hacked?",
  ])("keeps conversational database intent off the AI provider path: %s", async (question) => {
    const fetchImpl = () => Promise.reject(new Error("provider must not be called"));
    const openAi = new OpenAiIntentProvider({ apiKey: "unused", model: "test", fetchImpl });
    await expect(openAi.resolve(question)).resolves.toMatchObject({ status: "ready", intent: { intent: "aggregate" } });
  });
});

function analyticsEvent(
  id: string,
  title: string,
  asset: Asset,
  category: EventCategory,
  publishedAt: string,
): AnalyticsEvent {
  return {
    eventId: id,
    slug: id,
    title,
    publishedAt,
    assets: [asset],
    primaryAsset: asset,
    category,
    sourceClass: "news_media",
    sentiment: null,
    importance: null,
    reactionV2: {
      BTC: { "1m": 1, "5m": 1, "15m": 1, "1h": 1, "4h": 1, "24h": 1 },
      ETH: { "1m": 1, "5m": 1, "15m": 1, "1h": 1, "4h": 1, "24h": 1 },
      SOL: { "1m": 1, "5m": 1, "15m": 1, "1h": 1, "4h": 1, "24h": 1 },
    },
  };
}

function intent(asset: Asset, topic: AiTopic, overrides: Partial<AiSearchIntent> = {}): AiSearchIntent {
  return validateIntent({
    intent: "search", asset, dateFrom: null, dateTo: null, category: null, topic,
    actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown", amount: null,
    entity: null, assetRole: "primary", sourceClass: null, sentiment: null, reactionSign: null,
    importance: null, horizon: null, metric: "events", sort: "newest", groupBy: "none",
    comparison: null, limit: 10, ...overrides,
  });
}

describe("AI Topic Matching Quality V2 — precision and false-zero guards", () => {
  const events = [
    analyticsEvent("approval", "SEC approves spot Bitcoin ETF", "BTC", "official_decision", "2024-01-01T00:00:00Z"),
    analyticsEvent("outflow", "Bitcoin ETFs post record outflows", "BTC", "etf", "2026-01-01T00:00:00Z"),
    analyticsEvent("rejection", "SEC rejects proposed Bitcoin ETF", "BTC", "official_decision", "2025-01-01T00:00:00Z"),
    analyticsEvent("delay", "SEC delays decision on Bitcoin ETF", "BTC", "regulation", "2025-06-01T00:00:00Z"),
    analyticsEvent("hack", "Solana bridge hacked in security exploit", "SOL", "security_event", "2025-05-01T00:00:00Z"),
    analyticsEvent("warning", "Solana bridge warns of potential hack", "SOL", "security", "2026-05-01T00:00:00Z"),
    analyticsEvent("hike", "Bitcoin falls as Fed raises rates", "BTC", "macro", "2025-04-01T00:00:00Z"),
    analyticsEvent("cut", "Bitcoin rallies after Fed rate cut", "BTC", "macro", "2025-03-01T00:00:00Z"),
  ];

  it.each([
    ["etf_approval", ["approval"]],
    ["etf_rejection", ["rejection"]],
    ["etf_delay", ["delay"]],
    ["fed_rate_hike", ["hike"]],
    ["fed_rate_cut", ["cut"]],
  ] as const)("keeps %s precise", (topic, expected) => {
    const result = runAnalytics(events, intent("BTC", topic));
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(expected);
  });

  it("does not turn ETF outflow into ETF approval", () => {
    const result = runAnalytics(events, intent("BTC", "etf_outflow", { actorType: "ETF", action: "withdraw", direction: "outflow" }));
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(["outflow"]);
  });

  it("accepts hack/exploit aliases despite a provider-supplied flow direction and rejects warnings", () => {
    const result = runAnalytics(events, intent("SOL", "hack", { action: "hack", direction: "outflow" }));
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(["hack"]);
  });

  it("uses ETF approval as a bounded regulatory-approval fallback", () => {
    const result = runAnalytics([
      analyticsEvent("eth-etf", "Spot Ethereum ETF gets approved", "ETH", "etf", "2025-01-01T00:00:00Z"),
      analyticsEvent("eth-flow", "Ethereum ETFs post record inflows", "ETH", "etf", "2026-01-01T00:00:00Z"),
    ], intent("ETH", "regulatory_approval", { action: "approve", direction: "neutral" }));
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(["eth-etf"]);
  });

  it("ranks category-aligned direct matches before newer weak matches", () => {
    const result = runAnalytics([
      analyticsEvent("direct", "Institutional fund buys $90M ETH", "ETH", "institutional", "2025-01-01T00:00:00Z"),
      analyticsEvent("weak", "Company buys $90M ETH", "ETH", "news", "2026-01-01T00:00:00Z"),
    ], intent("ETH", "institutional_purchase", { action: "buy", direction: "inflow" }));
    expect(result.citations.map(({ eventId }) => eventId)).toEqual(["direct", "weak"]);
  });
});
