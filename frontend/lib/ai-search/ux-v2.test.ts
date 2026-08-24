import { describe, expect, it } from "vitest";

import { groundedAnswer } from "@/lib/ai-search/answer";
import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { MockAiIntentProvider } from "@/lib/ai-search/provider";
import { executeAiSearch } from "@/lib/ai-search/service";

const provider = new MockAiIntentProvider();
const adapter = new FixtureAiSearchDataAdapter();

describe("AI Search usable defaults", () => {
  it("returns all six horizons for a Ukrainian ETH ETF reaction query", async () => {
    const response = await executeAiSearch("Як ETH зазвичай реагує на ETF news?", provider, adapter);
    expect(response.statusCode).toBe(200);
    if (response.statusCode !== 200) throw new Error("Expected a grounded result");
    expect(response.body.intent).toMatchObject({ asset: "ETH", category: "etf", horizon: null, metric: "mean" });
    expect(response.body.result).toMatchObject({ kind: "multi_horizon" });
    if (response.body.result.kind !== "multi_horizon") throw new Error("Expected multi-horizon analytics");
    expect(response.body.result.rows.map(({ horizon }) => horizon)).toEqual(["1m", "5m", "15m", "1h", "4h", "24h"]);
  });

  it("counts positive ETH events across the full stated year", async () => {
    const response = await executeAiSearch("How many positive ETH events were there in 2023?", provider, adapter);
    expect(response).toMatchObject({ statusCode: 200, body: { intent: { asset: "ETH", metric: "count", dateFrom: "2023-01-01", dateTo: "2023-12-31" } } });
  });

  it("uses only explicit 24h for ETH SEC filings in 2024", async () => {
    const response = await executeAiSearch("How did ETH react to SEC filings in 2024 after 24h?", provider, adapter);
    expect(response).toMatchObject({ statusCode: 200, body: { intent: { asset: "ETH", category: "regulation", horizon: "24h", metric: "mean" }, result: { kind: "scalar" } } });
  });

  it("uses a human empty state when no events match", async () => {
    const response = await executeAiSearch("How did ETH react to hacks in 2022 after 24h?", provider, adapter);
    expect(response).toMatchObject({ statusCode: 200, body: { answer: "No matching historical events found.", calculation: "" } });
  });

  it("rounds percentages to at most two decimals", () => {
    const output = groundedAnswer({ kind: "share", positivePercent: 33.333333, negativePercent: 66.666667, neutralPercent: 0, sampleSize: 3, unit: "percent", citations: [] });
    expect(output.answer).toBe("Positive: 33.33%; negative: 66.67%; neutral: 0%.");
  });
});
