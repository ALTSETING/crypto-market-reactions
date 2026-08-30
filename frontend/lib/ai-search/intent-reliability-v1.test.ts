import { describe, expect, it, vi } from "vitest";

import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { applyExplicitQuestionDefaults } from "@/lib/ai-search/intent-defaults";
import { MockAiIntentProvider, OpenAiIntentProvider } from "@/lib/ai-search/provider";
import { executeAiSearch } from "@/lib/ai-search/service";
import type { AiSearchIntent } from "@/types/ai-search";

const provider = new MockAiIntentProvider();
const adapter = new FixtureAiSearchDataAdapter();

const BASE_INTENT: AiSearchIntent = {
  intent: "aggregate", asset: "SOL", dateFrom: null, dateTo: null, category: null,
  topic: "hack", actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
  amount: null, entity: null, assetRole: "primary", sourceClass: null, sentiment: null,
  reactionSign: null, importance: null, horizon: "1m", metric: "mean", sort: "newest",
  groupBy: "none", comparison: null, limit: 10,
};

describe("AI Intent Reliability V1 regression matrix", () => {
  it.each([
    ["How did Bitcoin react 24 hours after major ETF inflows?", { asset: "BTC", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: "24h" }],
    ["How does BTC react to ETF outflows?", { asset: "BTC", topic: "etf_outflow", direction: "outflow", action: "withdraw", horizon: null }],
    ["How does ETH react to sales by large investors?", { asset: "ETH", topic: "institutional_selling", direction: "outflow", action: "sell", horizon: null }],
    ["How does ETH react to institutional buying?", { asset: "ETH", topic: "institutional_purchase", direction: "inflow", action: "buy", horizon: null }],
    ["How does SOL react to hacks?", { asset: "SOL", topic: "hack", direction: "unknown", action: null, horizon: null }],
    ["How does ETH react to large institutional purchases?", { asset: "ETH", topic: "institutional_purchase", direction: "inflow", action: "buy", horizon: null }],
    ["How does BTC react to ETF inflows?", { asset: "BTC", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: null }],
    ["How does SOL react to large purchases?", { asset: "SOL", topic: "large_investment", direction: "inflow", action: "buy", horizon: null }],
    ["Як BTC реагує на припливи в ETF?", { asset: "BTC", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: null }],
    ["Як BTC реагує на надходження в ETF?", { asset: "BTC", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: null }],
    ["Як BTC реагує на відтоки з ETF?", { asset: "BTC", topic: "etf_outflow", direction: "outflow", action: "withdraw", horizon: null }],
    ["Як BTC реагує на виведення коштів з ETF?", { asset: "BTC", topic: "etf_outflow", direction: "outflow", action: "withdraw", horizon: null }],
    ["Як ETH реагує на продажі великими інвесторами?", { asset: "ETH", topic: "institutional_selling", direction: "outflow", action: "sell", horizon: null }],
    ["Як ETH реагує на розпродажі великими інвесторами?", { asset: "ETH", topic: "institutional_selling", direction: "outflow", action: "sell", horizon: null }],
    ["Як SOL реагує на великі покупки?", { asset: "SOL", topic: "large_investment", direction: "inflow", action: "buy", horizon: null }],
    ["Як BTC реагує на припливи в ETF через 24 години?", { asset: "BTC", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: "24h" }],
    ["Як ETH реагує на інституційні купівлі через добу?", { asset: "ETH", topic: "institutional_purchase", direction: "inflow", action: "buy", horizon: "24h" }],
    ["How does ETH react to ETF inflows after 1 hour?", { asset: "ETH", topic: "etf_inflow", direction: "inflow", action: "deposit", horizon: "1h" }],
    ["How does BTC react to ETF outflows 5 minutes later?", { asset: "BTC", topic: "etf_outflow", direction: "outflow", action: "withdraw", horizon: "5m" }],
    ["Як SOL реагує на злами через 15 хвилин?", { asset: "SOL", topic: "hack", direction: "unknown", action: null, horizon: "15m" }],
    ["How does ETH react to institutional selling 4 hours later?", { asset: "ETH", topic: "institutional_selling", direction: "outflow", action: "sell", horizon: "4h" }],
  ] as const)("preserves deterministic constraints for %s", async (question, expected) => {
    await expect(provider.resolve(question)).resolves.toMatchObject({ status: "ready", intent: expected });
  });

  it("preserves an explicit year and natural-language horizon together", () => {
    const resolution = applyExplicitQuestionDefaults("How did ETH react to ETF inflows in 2024 after 24 hours?", {
      status: "ready",
      intent: { ...BASE_INTENT, asset: "BTC", topic: "etf_outflow", direction: "outflow", horizon: "1m" },
    });
    expect(resolution).toMatchObject({
      status: "ready",
      intent: { asset: "ETH", topic: "etf_inflow", direction: "inflow", horizon: "24h", dateFrom: "2024-01-01", dateTo: "2024-12-31" },
    });
  });

  it("does not call OpenAI for the previously broken production example", async () => {
    const fetchImpl = vi.fn();
    const openAi = new OpenAiIntentProvider({ apiKey: "unused", model: "test", fetchImpl });
    await expect(openAi.resolve("How does ETH react to sales by large investors?")).resolves.toMatchObject({
      status: "ready",
      intent: { asset: "ETH", topic: "institutional_selling", direction: "outflow", action: "sell", horizon: null },
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ["How does BTC react to ETF inflows and outflows?", "Please choose either inflows or outflows."],
    ["How does ETH react to institutional buying and selling?", "Please choose either buying or selling."],
    ["How does SOL react to hacks after 2 hours?", "Use one supported horizon: 1m, 5m, 15m, 1h, 4h or 24h."],
  ] as const)("returns a safe clarification for %s", async (question, message) => {
    await expect(executeAiSearch(question, provider, adapter)).resolves.toMatchObject({
      statusCode: 422,
      body: { status: "clarification", code: "CLARIFICATION_REQUIRED", message },
    });
  });

  it("returns all horizons only when no horizon was stated", async () => {
    const all = await executeAiSearch("How does BTC react to ETF inflows?", provider, adapter);
    const one = await executeAiSearch("How does BTC react to ETF inflows after 24 hours?", provider, adapter);
    expect(all).toMatchObject({ statusCode: 200, body: { intent: { horizon: null }, result: { kind: "multi_horizon" } } });
    expect(one).toMatchObject({ statusCode: 200, body: { intent: { horizon: "24h" }, result: { kind: "scalar" } } });
  });
});
