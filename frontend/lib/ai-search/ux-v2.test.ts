import { describe, expect, it } from "vitest";

import { groundedAnswer } from "@/lib/ai-search/answer";
import { applyExplicitQuestionDefaults } from "@/lib/ai-search/intent-defaults";
import type { IntentResolution } from "@/types/ai-search";

const clarification: IntentResolution = { status: "clarification", message: "Specify dateFrom and metric enum." };

describe("AI Search V2 UX defaults", () => {
  it("keeps explicit ETH, SEC, 2024, and 24h without clarification", () => {
    expect(applyExplicitQuestionDefaults("How did ETH react to SEC filings in 2024 after 24h?", clarification)).toMatchObject({
      status: "ready",
      intent: { asset: "ETH", category: "regulation", dateFrom: "2024-01-01", dateTo: "2024-12-31", horizon: "24h", metric: "mean" },
    });
  });

  it("defaults positive ETH events in 2023 to count", () => {
    expect(applyExplicitQuestionDefaults("How many positive ETH events were there in 2023?", clarification)).toMatchObject({
      status: "ready",
      intent: { asset: "ETH", sentiment: "positive", dateFrom: "2023-01-01", dateTo: "2023-12-31", metric: "count" },
    });
  });

  it("defaults 10 SOL news-media drops at 1h to losers ranking", () => {
    expect(applyExplicitQuestionDefaults("Show 10 biggest SOL drops after news media at 1h", clarification)).toMatchObject({
      status: "ready",
      intent: { asset: "SOL", sourceClass: "news_media", horizon: "1h", intent: "rank", sort: "losers", limit: 10 },
    });
  });

  it("understands Ukrainian ETH and ETF while asking only for horizon", () => {
    expect(applyExplicitQuestionDefaults("Як ефір реагував на новини про ETF?", clarification)).toEqual({
      status: "clarification",
      message: "Which reaction horizon should I use: 1h, 4h or 24h?",
    });
  });

  it("rounds percentages to at most two decimals", () => {
    const output = groundedAnswer({ kind: "share", positivePercent: 33.333333, negativePercent: 66.666667, neutralPercent: 0, sampleSize: 3, unit: "percent", citations: [] });
    expect(output.answer).toBe("Positive: 33.33%; negative: 66.67%; neutral: 0%.");
  });
});
