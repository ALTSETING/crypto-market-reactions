import { describe, expect, it, vi } from "vitest";

import { OpenAiIntentProvider } from "@/lib/ai-search/provider";

const validIntent = {
  intent: "count", asset: "ETH", dateFrom: "2023-01-01", dateTo: "2023-12-31",
  category: null, topic: null, sourceClass: null, sentiment: null, reactionSign: "positive", importance: null,
  horizon: "24h", metric: "count", sort: "newest", groupBy: "none", comparison: null, limit: 10,
};
const validResolution = { status: "ready", intent: validIntent, message: null };

describe("server-only OpenAI provider boundary", () => {
  it("uses structured output, store=false, environment-supplied model, and no more than one retry", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response("temporary", { status: 503 }))
      .mockResolvedValueOnce(Response.json({
        model: "test-model",
        output_text: JSON.stringify(validResolution),
        usage: { input_tokens: 100, output_tokens: 40, total_tokens: 140, input_tokens_details: { cached_tokens: 0 } },
      }));
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const onUsage = vi.fn();
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "test-model", fetchImpl, timeoutMs: 500, onUsage });
    await expect(provider.resolve("How many positive ETH events were there in 2023?")).resolves.toEqual({ status: "ready", intent: validIntent });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const request = JSON.parse(fetchImpl.mock.calls[0][1]?.body as string);
    expect(request).toMatchObject({ model: "test-model", store: false, max_output_tokens: 500, reasoning: { effort: "minimal" }, text: { format: { type: "json_schema", strict: true } } });
    expect(request).not.toHaveProperty("tools");
    expect(onUsage).toHaveBeenCalledWith(expect.objectContaining({ model: "test-model", inputTokens: 100, outputTokens: 40 }));
    expect(JSON.stringify(onUsage.mock.calls)).not.toContain("How many positive");
  });

  it("does not retry deterministic client errors", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("bad", { status: 400 }));
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "test-model", fetchImpl });
    await expect(provider.resolve("question")).resolves.toMatchObject({ status: "rejected" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("refuses a request before calling OpenAI when the configured cost cap is too low", async () => {
    const fetchImpl = vi.fn();
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "test-model", fetchImpl, maxCostUsd: 0.00001 });
    await expect(provider.resolve("Find BTC events")).resolves.toMatchObject({ status: "rejected" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not retry malformed structured output", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({ output_text: "not-json" }));
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "test-model", fetchImpl });
    await expect(provider.resolve("Find BTC events")).resolves.toMatchObject({ status: "rejected" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
