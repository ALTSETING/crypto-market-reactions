import { describe, expect, it, vi } from "vitest";

import { OpenAiResearchRouter } from "@/lib/ai-search/router";
import { validateRouterDecision } from "@/lib/ai-search/router-schema";

const VALID_GENERAL = {
  route: "general",
  language: "en",
  generalTopic: "general_crypto",
  databaseIntent: null,
  needsHistoricalAnalysis: false,
  needsGeneralExplanation: true,
  clarificationQuestion: null,
  refusalReason: null,
} as const;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("AI Research router schema and provider", () => {
  it("accepts only exact, internally consistent allowlisted decisions", () => {
    expect(validateRouterDecision(VALID_GENERAL)).toEqual(VALID_GENERAL);
    expect(() => validateRouterDecision({ ...VALID_GENERAL, route: "database" })).toThrow();
    expect(() => validateRouterDecision({ ...VALID_GENERAL, extra: true })).toThrow();
    expect(() => validateRouterDecision({ ...VALID_GENERAL, generalTopic: "trading_signal" })).toThrow();
    expect(() => validateRouterDecision({ ...VALID_GENERAL, databaseIntent: { asset: null, horizon: null, topic: null, direction: "unknown", dateFrom: "yesterday", dateTo: null } })).toThrow();
  });

  it("detects Ukrainian questions even when they contain no Ukrainian-specific letter", async () => {
    await expect(new OpenAiResearchRouter({ apiKey: "unused", model: "gpt-5-mini", fetchImpl: vi.fn() }).resolve("Що таке Ethereum?")).resolves.toMatchObject({ route: "general", language: "uk" });
  });

  it("uses the server-side Responses API contract with storage disabled", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      expect(request.store).toBe(false);
      expect(request.text.format.type).toBe("json_schema");
      expect(request.text.format.strict).toBe(true);
      expect(JSON.stringify(init?.headers)).not.toContain("question");
      return response({ output_text: JSON.stringify(VALID_GENERAL), model: "gpt-5-mini", usage: { input_tokens: 20, output_tokens: 10, total_tokens: 30 } });
    });
    const router = new OpenAiResearchRouter({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl });
    await expect(router.resolve("Tell me about crypto custody")).resolves.toMatchObject({ route: "general", language: "en" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("performs at most one retry and fails closed on invalid provider output", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({}, 500))
      .mockResolvedValueOnce(response({ output_text: "{}" }));
    const router = new OpenAiResearchRouter({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl });
    await expect(router.resolve("Tell me about crypto custody")).rejects.toThrow("temporarily unavailable");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("never lets AI override explicit database constraints", async () => {
    const aiDecision = {
      route: "database", language: "en", generalTopic: null,
      databaseIntent: { asset: "SOL", horizon: "1m", topic: "etf_outflow", direction: "outflow", dateFrom: null, dateTo: null },
      needsHistoricalAnalysis: true, needsGeneralExplanation: false, clarificationQuestion: null, refusalReason: null,
    };
    const fetchImpl = vi.fn(async () => response({ output_text: JSON.stringify(aiDecision) }));
    const router = new OpenAiResearchRouter({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl });
    // This wording deliberately avoids the local historical verbs so the strict AI merge path is exercised.
    const result = await router.resolve("ETF inflows, 24h, 2024 — crypto research please");
    expect(result.databaseIntent).toMatchObject({ asset: null, horizon: "24h", topic: "etf_inflow", direction: "inflow", dateFrom: "2024-01-01", dateTo: "2024-12-31" });
  });
});
