import { afterEach, describe, expect, it, vi } from "vitest";

import { OpenAiIntentProvider } from "@/lib/ai-search/provider";

const validIntent = {
  intent: "count", asset: "ETH", dateFrom: "2023-01-01", dateTo: "2023-12-31",
  category: null, topic: null, actorType: "unknown", action: null, direction: "unknown", magnitude: "unknown",
  amount: null, entity: null, assetRole: "primary", sourceClass: null, sentiment: null, reactionSign: "positive", importance: null,
  horizon: "24h", metric: "count", sort: "newest", groupBy: "none", comparison: null, limit: 10,
};
const validResolution = { status: "ready", intent: validIntent, message: null };

describe("server-only OpenAI provider boundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses structured output, store=false, environment-supplied model, and no more than one retry", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response("temporary", { status: 503 }))
      .mockResolvedValueOnce(Response.json({
        model: "gpt-5-mini",
        output_text: JSON.stringify(validResolution),
        usage: { input_tokens: 100, output_tokens: 40, total_tokens: 140, input_tokens_details: { cached_tokens: 0 } },
      }));
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const onUsage = vi.fn();
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "gpt-5-mini", fetchImpl, timeoutMs: 500, onUsage });
    await expect(provider.resolve("How many positive ETH events were there in 2023?")).resolves.toEqual({ status: "ready", intent: validIntent });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const request = JSON.parse(fetchImpl.mock.calls[0][1]?.body as string);
    expect(request).toMatchObject({ model: "gpt-5-mini", store: false, max_output_tokens: 500, reasoning: { effort: "minimal" }, text: { format: { type: "json_schema", strict: true } } });
    expect(request).not.toHaveProperty("response_format");
    expect(request).not.toHaveProperty("tools");
    expect(onUsage).toHaveBeenCalledWith(expect.objectContaining({ model: "gpt-5-mini", inputTokens: 100, outputTokens: 40 }));
    expect(JSON.stringify(onUsage.mock.calls)).not.toContain("How many positive");
    const [endpoint, init] = fetchImpl.mock.calls[0];
    const sanitizedTransport = {
      endpoint,
      method: init?.method,
      headerNames: Object.keys(init?.headers as Record<string, string>).sort(),
      bodyKeys: Object.keys(request).sort(),
    };
    expect(sanitizedTransport).toMatchInlineSnapshot(`
      {
        "bodyKeys": [
          "input",
          "instructions",
          "max_output_tokens",
          "model",
          "reasoning",
          "store",
          "text",
        ],
        "endpoint": "https://api.openai.com/v1/responses",
        "headerNames": [
          "Authorization",
          "Content-Type",
        ],
        "method": "POST",
      }
    `);
    expect(JSON.stringify(sanitizedTransport)).not.toMatch(/test-server-key|How many positive|Convert the English/iu);
  });

  it("does not retry deterministic client errors", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({ error: { message: "raw secret-bearing error" } }, { status: 400 }));
    const onDiagnostic = vi.fn();
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "gpt-5-mini", fetchImpl, onDiagnostic });
    await expect(provider.resolve("private question")).resolves.toEqual({
      status: "rejected",
      message: "The AI intent provider is temporarily unavailable.",
      diagnosticCode: "OPENAI_400_BAD_REQUEST",
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(onDiagnostic).toHaveBeenCalledWith(expect.objectContaining({ category: "OPENAI_400_BAD_REQUEST", httpStatus: 400 }));
    expect(JSON.stringify(onDiagnostic.mock.calls)).not.toMatch(/test-server-key|private question|raw secret-bearing error/iu);
  });

  it("refuses a request before calling OpenAI when the configured cost cap is too low", async () => {
    const fetchImpl = vi.fn();
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "gpt-5-mini", fetchImpl, maxCostUsd: 0.00001 });
    await expect(provider.resolve("Find BTC events")).resolves.toMatchObject({ status: "rejected" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("does not retry malformed structured output", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({ output_text: "not-json" }));
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "gpt-5-mini", fetchImpl });
    await expect(provider.resolve("Find BTC events")).resolves.toMatchObject({ status: "rejected" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("accepts the raw Responses API output array without output_text convenience", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({
      model: "gpt-5-mini",
      output: [{ content: [{ type: "output_text", text: JSON.stringify(validResolution) }] }],
      usage: { input_tokens: 80, output_tokens: 30, total_tokens: 110 },
    }));
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const provider = new OpenAiIntentProvider({ apiKey: "test-server-key", model: "gpt-5-mini", fetchImpl });
    await expect(provider.resolve("How many positive ETH events were there in 2023?")).resolves.toEqual({ status: "ready", intent: validIntent });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
