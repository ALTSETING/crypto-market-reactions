import type { AnalyticsEvent } from "@/types/ai-search";
import type { Asset, Horizon } from "@/types/events";

const empty = (): Record<Asset, Record<Horizon, number | null>> => ({
  BTC: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
  ETH: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
  SOL: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
});

function fixture(
  core: Omit<AnalyticsEvent, "reactionV2">,
  reactions: Partial<Record<Asset, Partial<Record<Horizon, number | null>>>>,
): AnalyticsEvent {
  const reactionV2 = empty();
  for (const asset of Object.keys(reactions) as Asset[]) {
    Object.assign(reactionV2[asset], reactions[asset]);
  }
  return { ...core, reactionV2 };
}

export const AI_SEARCH_FIXTURES: readonly AnalyticsEvent[] = [
  fixture({ eventId: "evt-ai-001", slug: "sec-approves-spot-ether-etfs", title: "SEC 19b-4 filing approves spot Ether ETFs", publishedAt: "2024-05-23T21:00:00Z", assets: ["ETH", "BTC"], category: "regulation", sourceClass: "primary_document", sentiment: "positive", importance: "high" }, { ETH: { "1h": 2.4, "4h": 4.1, "24h": 6.2 }, BTC: { "4h": 1.1 } }),
  fixture({ eventId: "evt-ai-002", slug: "sec-delays-ether-etf-decision", title: "SEC filing delays Ether ETF decision", publishedAt: "2024-01-25T15:30:00Z", assets: ["ETH"], category: "regulation", sourceClass: "primary_document", sentiment: "negative", importance: "medium" }, { ETH: { "1h": -1.2, "4h": -2.5, "24h": -3.4 } }),
  fixture({ eventId: "evt-ai-003", slug: "ether-etf-filing-analysis", title: "Publishers analyze Ether ETF filing", publishedAt: "2024-03-12T10:00:00Z", assets: ["ETH"], category: "etf", sourceClass: "news_media", sentiment: "neutral", importance: "medium" }, { ETH: { "1h": 0.5, "4h": 1.8, "24h": null } }),
  fixture({ eventId: "evt-ai-004", slug: "ethereum-foundation-upgrade-notice", title: "Ethereum Foundation publishes upgrade notice", publishedAt: "2023-04-01T09:00:00Z", assets: ["ETH"], category: "protocol_upgrade", sourceClass: "official_announcement", sentiment: "positive", importance: "high" }, { ETH: { "1h": 1.5, "4h": 3, "24h": 4.4 } }),
  fixture({ eventId: "evt-ai-005", slug: "solana-network-outage", title: "Solana network outage reported", publishedAt: "2024-02-06T11:00:00Z", assets: ["SOL"], category: "network_activity", sourceClass: "news_media", sentiment: "negative", importance: "high" }, { SOL: { "1h": -7.8, "4h": -10.2, "24h": -12 } }),
  fixture({ eventId: "evt-ai-006", slug: "solana-validator-update", title: "Solana validator update announced", publishedAt: "2024-03-04T08:00:00Z", assets: ["SOL"], category: "protocol_update", sourceClass: "official_announcement", sentiment: "positive", importance: "medium" }, { SOL: { "1h": 3.2, "4h": 4.7, "24h": 2.9 } }),
  fixture({ eventId: "evt-ai-007", slug: "solana-market-rally", title: "Solana rallies after ecosystem news", publishedAt: "2024-03-18T17:00:00Z", assets: ["SOL"], category: "market_commentary", sourceClass: "news_media", sentiment: "positive", importance: "medium" }, { SOL: { "1h": 6.5, "4h": 8.1, "24h": 10.4 } }),
  fixture({ eventId: "evt-ai-008", slug: "bitcoin-etf-order", title: "Regulator publishes Bitcoin ETF order", publishedAt: "2024-01-10T21:00:00Z", assets: ["BTC"], category: "etf", sourceClass: "primary_document", sentiment: "positive", importance: "high" }, { BTC: { "1h": 1.8, "4h": 3.6, "24h": 5.1 } }),
  fixture({ eventId: "evt-ai-009", slug: "bitcoin-etf-news-coverage", title: "News media covers Bitcoin ETF flows", publishedAt: "2024-02-15T12:00:00Z", assets: ["BTC"], category: "etf", sourceClass: "news_media", sentiment: "positive", importance: "medium" }, { BTC: { "1h": 0.9, "4h": 2.2, "24h": 3.3 } }),
  fixture({ eventId: "evt-ai-010", slug: "bitcoin-exchange-security-event", title: "Exchange security event weighs on Bitcoin", publishedAt: "2023-11-07T06:00:00Z", assets: ["BTC"], category: "security_event", sourceClass: "news_media", sentiment: "negative", importance: "high" }, { BTC: { "1h": -2.6, "4h": -4.4, "24h": -6.8 } }),
  fixture({ eventId: "evt-ai-011", slug: "ether-staking-update", title: "Ether staking update published", publishedAt: "2023-08-18T14:00:00Z", assets: ["ETH"], category: "staking", sourceClass: "news_media", sentiment: "positive", importance: "low" }, { ETH: { "1h": 0, "4h": 0.7, "24h": 1.3 } }),
  fixture({ eventId: "evt-ai-012", slug: "solana-report-without-one-hour-data", title: "Solana ecosystem report published", publishedAt: "2024-04-02T14:00:00Z", assets: ["SOL"], category: "news", sourceClass: "news_media", sentiment: "neutral", importance: "low" }, { SOL: { "4h": 0.4, "24h": 0.8 } }),
] as const;
